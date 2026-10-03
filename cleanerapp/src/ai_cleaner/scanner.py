"""Background scanner thread."""

import os
import time
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from .config import CONFIDENCE_RULE
from .minecraft import is_orphan_mod
from .protection import (
    GAME_DIRS,
    GAME_EXTS,
    GAME_PATH_HINTS,
    in_pseudo_fs,
    in_system_path,
    is_dpkg_owned,
    is_screenshot,
    sniff_file_kind,
)
from .state import extract_state, plain_reason

# Screenshots older than this many days get flagged automatically.
# Change to taste. 30 is a good balance — recent ones stay safe.
SCREENSHOT_MIN_AGE_DAYS = 30

# ETA tuning
ETA_ALPHA = 0.15  # EMA smoothing — lower = smoother, higher = more reactive
ETA_WARMUP_FILES = 300  # don't show an ETA until this many files are scanned
ETA_WARMUP_SECONDS = 2.0  # ...or this many seconds, whichever is later

# Batching config — how many files to accumulate before firing a Qt signal.
# Larger = fewer signals but chunkier UI updates.
BATCH_MIN_FILES = 25
BATCH_MIN_SECONDS = 0.15

# Set this to False once wizard.py connects to `files_found` instead of
# `file_found`. Emitting the legacy per-item signal costs ~1 µs/file —
# noticeable at 100k+ files.
EMIT_LEGACY_FILE_SIGNAL = True


class ScannerThread(QThread):
    progress = pyqtSignal(int, int, str, float, bool)
    file_found = pyqtSignal(dict)  # legacy, per-item — will be removed
    files_found = pyqtSignal(list)  # new, batched
    finished_scan = pyqtSignal(list)
    status = pyqtSignal(str)

    def __init__(self, root_path, agent, rules, deep_mode=False):
        super().__init__()
        self.root_path = root_path
        self.agent = agent
        self.rules = rules
        self.deep_mode = deep_mode
        self._running = True

    def stop(self):
        self._running = False

    @staticmethod
    def _is_protected(path):
        p = str(path).lower()
        if any(g and g.lower() in p for g in GAME_DIRS):
            return True
        if any(h in p for h in GAME_PATH_HINTS):
            return True
        return path.suffix.lower() in GAME_EXTS

    def _should_prune_dir(self, dirpath, dirname):
        full = os.path.join(dirpath, dirname)
        if in_pseudo_fs(full):
            return True
        if in_system_path(full):
            return True
        if not self.deep_mode and dirname.startswith("."):  # noqa: SIM102
            if dirname not in (".local", ".cache"):
                return True
        low = full.lower()
        if any(g and g.lower() in low for g in GAME_DIRS):
            return True
        return bool(any(h in low for h in GAME_PATH_HINTS))

    def _count_files(self, root):
        n = 0
        t_last = time.time()
        for dp, dns, fns in os.walk(root, onerror=lambda e: None):
            if not self._running:
                break
            dns[:] = [d for d in dns if not self._should_prune_dir(dp, d)]
            n += len(fns)
            now = time.time()
            if now - t_last > 0.2:
                self.progress.emit(n, 0, dp, 0.0, True)
                t_last = now
        return n

    def run(self):
        root = Path(self.root_path).expanduser().resolve()
        self.status.emit("Counting files…")
        total = self._count_files(root)
        if not self._running:
            self.finished_scan.emit([])
            return
        self.status.emit(f"Analyzing {total:,} files…")

        screenshot_age_days = int(
            self.rules.settings.get("screenshot_min_age_days", SCREENSHOT_MIN_AGE_DAYS)
        )

        manual = float(self.rules.settings.get("min_confidence", -1))
        if manual < 0:
            # This is only the *fallback* threshold. The scanner uses
            # dynamic_threshold(state=state) per file when this is < 0.
            min_confidence = self.agent.dynamic_threshold()
            self.status.emit(
                f"AI threshold (fallback): {min_confidence:.2f} "
                f"({self.agent.calibration_summary()})"
            )
        else:
            min_confidence = manual
            self.status.emit(f"Manual confidence threshold: {min_confidence:.2f}")

        results = []
        pending = []
        scanned = 0
        t0 = time.time()
        last_emit = 0.0
        last_batch = time.time()

        # --- ETA state (true instantaneous rate, EMA-smoothed) ---
        ema_rate = None
        last_sample_scanned = 0
        last_sample_time = t0

        def flush_batch(force=False):
            if not pending:
                return None
            now = time.time()
            if (
                not force
                and len(pending) < BATCH_MIN_FILES
                and (now - last_batch) < BATCH_MIN_SECONDS
            ):
                return None
            batch = list(pending)
            self.files_found.emit(batch)
            if EMIT_LEGACY_FILE_SIGNAL:
                for info in batch:
                    self.file_found.emit(info)
            pending.clear()
            return now

        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            if not self._running:
                break
            dirnames[:] = [
                d for d in dirnames if not self._should_prune_dir(dirpath, d)
            ]

            for fname in filenames:
                if not self._running:
                    break
                scanned += 1
                fpath = Path(dirpath) / fname

                # 1. rules first
                rule_action, rule = self.rules.match(fpath)
                if rule_action == "protect":
                    continue
                if rule_action == "flag":
                    try:
                        st = fpath.stat()
                        info = {
                            "path": str(fpath),
                            "name": fpath.name,
                            "size": st.st_size,
                            "age": int((time.time() - st.st_mtime) / 86400.0),
                            "state": None,
                            "kind": None,
                            "confidence": CONFIDENCE_RULE,
                            "reason": rule.get("note")
                            or f"Your rule: {rule.get('value', '')}",
                        }
                        results.append(info)
                        pending.append(info)
                    except (PermissionError, OSError):
                        pass
                    continue

                    # 1b. Orphaned Minecraft mods — high-confidence cleanup.
                # Mods you downloaded manually and never removed after
                # changing modpacks.  Detected structurally, not by AI.
                if fpath.suffix.lower() == ".jar" and is_orphan_mod(fpath):
                    try:
                        st = fpath.stat()
                        size = st.st_size
                        age = (time.time() - st.st_mtime) / 86400.0
                        state = extract_state(fpath, size, age)
                        info = {
                            "path": str(fpath),
                            "name": fpath.name,
                            "size": size,
                            "age": int(age),
                            "state": state,
                            "kind": "minecraft-mod",
                            "confidence": CONFIDENCE_RULE,
                            "reason": (
                                f"A mod you haven't used in {int(age)} days "
                                "— not loaded by any Minecraft instance"
                            ),
                        }
                        results.append(info)
                        pending.append(info)
                    except (PermissionError, OSError):
                        pass
                    continue

                # 2. hardcoded protection + sniffing
                try:
                    if not fpath.is_file():
                        continue
                    if self._is_protected(fpath):
                        continue
                    if in_system_path(fpath):
                        continue
                    if is_dpkg_owned(fpath):
                        continue

                    kind, _preview = sniff_file_kind(fpath)
                    if kind in (
                        "text-code",
                        "binary-exec",
                        "unreadable",
                        "critical",
                        "office-doc",
                    ):
                        continue

                    st = fpath.stat()
                    size = st.st_size
                    age = (time.time() - st.st_mtime) / 86400.0
                    state = extract_state(fpath, size, age)

                    if (
                        screenshot_age_days > 0
                        and is_screenshot(fpath)
                        and age > screenshot_age_days
                    ):
                        info = {
                            "path": str(fpath),
                            "name": fpath.name,
                            "size": size,
                            "age": int(age),
                            "state": state,
                            "confidence": CONFIDENCE_RULE,
                            "reason": (
                                f"An old screenshot "
                                f"({int(age)} days) — probably no longer needed"
                            ),
                        }
                        results.append(info)
                        pending.append(info)
                        continue

                    if self.agent.act(state, explore=False) == 1:
                        conf = self.agent.confidence(state)
                        # Prefer the per-context threshold when the AI is
                        # choosing; fall back to the global one otherwise.
                        if manual < 0:
                            threshold = self.agent.dynamic_threshold(state=state)
                        else:
                            threshold = min_confidence
                        if threshold > 0 and conf < threshold:
                            continue
                        info = {
                            "path": str(fpath),
                            "name": fpath.name,
                            "size": size,
                            "age": int(age),
                            "state": state,
                            "kind": kind,
                            "confidence": conf,
                            "reason": plain_reason(fpath, size, int(age)),
                        }
                        results.append(info)
                        pending.append(info)
                except (PermissionError, OSError, FileNotFoundError):
                    continue

                now = time.time()

                # --- batched signal flush ---
                flushed_at = flush_batch()
                if flushed_at:
                    last_batch = flushed_at

                # --- progress / ETA ---
                if now - last_emit > 0.15:
                    # True instantaneous rate since the last sample.
                    delta_files = scanned - last_sample_scanned
                    delta_t = now - last_sample_time
                    if delta_t > 0.2:
                        instant_rate = delta_files / delta_t
                        if ema_rate is None:
                            ema_rate = instant_rate
                        else:
                            ema_rate = (
                                ETA_ALPHA * instant_rate + (1 - ETA_ALPHA) * ema_rate
                            )
                        last_sample_scanned = scanned
                        last_sample_time = now

                    ready = (
                        ema_rate is not None
                        and ema_rate > 0
                        and scanned >= ETA_WARMUP_FILES
                        and (now - t0) >= ETA_WARMUP_SECONDS
                    )
                    if ready:
                        remaining = max(0, total - scanned)
                        eta = remaining / ema_rate
                    else:
                        eta = -1.0

                    self.progress.emit(scanned, total, dirpath, eta, False)
                    last_emit = now

        # Final flush so nothing gets stranded
        flush_batch(force=True)
        self.progress.emit(scanned, total, "", 0.0, False)
        self.finished_scan.emit(results)
