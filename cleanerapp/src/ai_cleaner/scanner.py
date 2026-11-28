"""Background scanner thread.

Walk each selected tree once, pruning protected directories before descending.
The Q-learning agent makes one prediction per eligible file; only user feedback
changes the learned policy during normal use.
"""

import os
import time
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal

from .config import CONFIDENCE_RULE
from .minecraft import is_orphan_mod
from .protection import (
    GAME_EXTS,
    is_hard_protected_path,
    is_hard_protected_file,
    is_dpkg_owned,
    is_screenshot,
    sniff_file_kind,
)
from .state import extract_state, plain_reason
from .virtualmachines import VM_DISK_EXTS, is_vm_leftover


SCREENSHOT_MIN_AGE_DAYS = 30
ORPHAN_MIN_AGE_DAYS = 30

BATCH_MIN_FILES = 25
BATCH_MIN_SECONDS = 0.15

# wizard.py consumes the batched signal. Keep the legacy signal disabled:
# emitting once per file creates unnecessary Qt work on large scans.
EMIT_LEGACY_FILE_SIGNAL = False

PROTECTED_KINDS = {
    "text-code",
    "binary-exec",
    "unreadable",
    "critical",
    "office-doc",
}


class ScannerThread(QThread):
    progress = pyqtSignal(int, int, str, float, bool)
    file_found = pyqtSignal(dict)  # legacy, per-item signal
    files_found = pyqtSignal(list)
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
        path = Path(path)
        return (
            is_hard_protected_path(path)
            or path.suffix.lower() in GAME_EXTS
        )

    def _should_prune_dir(self, dirpath, dirname):
        """Do not descend into immutable or user-protected directories."""
        if dirname.startswith(".mount_"):
            # Temporary AppImage/FUSE mounts are not useful cleanup targets.
            return True

        full = Path(dirpath) / dirname

        if self._is_protected(full):
            return True

        try:
            action, _rule = self.rules.match(full)
        except (OSError, TypeError, ValueError):
            action = None

        if action == "protect":
            return True

        if not self.deep_mode and dirname.startswith("."):
            if dirname not in (".local", ".cache"):
                return True

        return False

    def _root_is_pruned(self, root):
        """Apply the same directory policy when the selected folder is the root."""
        if root.name.startswith(".mount_"):
            return True
        if self._is_protected(root):
            return True

        try:
            action, _rule = self.rules.match(root)
        except (OSError, TypeError, ValueError):
            action = None

        if action == "protect":
            return True

        if (
            not self.deep_mode
            and root.name.startswith(".")
            and root.name not in (".local", ".cache")
        ):
            return True

        return False

    def run(self):
        try:
            root = Path(self.root_path).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            self.status.emit("The selected folder could not be resolved.")
            self.finished_scan.emit([])
            return

        if self._root_is_pruned(root):
            self.status.emit("This folder is protected by your settings.")
            self.finished_scan.emit([])
            return

        if not root.is_dir():
            self.status.emit("Please select a folder to scan.")
            self.finished_scan.emit([])
            return

        self.status.emit("Analyzing files…")

        try:
            screenshot_age_days = int(
                self.rules.settings.get(
                    "screenshot_min_age_days",
                    SCREENSHOT_MIN_AGE_DAYS,
                )
            )
            manual = float(self.rules.settings.get("min_confidence", -1))
        except (AttributeError, TypeError, ValueError):
            screenshot_age_days = SCREENSHOT_MIN_AGE_DAYS
            manual = -1.0

        if manual < 0:
            min_confidence = self.agent.dynamic_threshold()
            self.status.emit(
                f"AI threshold: {min_confidence:.2f} "
                f"({self.agent.calibration_summary()})"
            )
        else:
            min_confidence = manual
            self.status.emit(f"Manual confidence threshold: {min_confidence:.2f}")

        results = []
        pending = []
        scanned = 0
        last_emit = 0.0
        last_batch = time.time()
        threshold_cache = {}

        def flush_batch(force=False):
            nonlocal last_batch

            if not pending:
                return

            now = time.time()
            if (
                not force
                and len(pending) < BATCH_MIN_FILES
                and now - last_batch < BATCH_MIN_SECONDS
            ):
                return

            batch = list(pending)
            self.files_found.emit(batch)

            if EMIT_LEGACY_FILE_SIGNAL:
                for info in batch:
                    self.file_found.emit(info)

            pending.clear()
            last_batch = now

        def add_result(info):
            results.append(info)
            pending.append(info)

        def make_rule_result(path, stat_result, rule):
            age_days = max(
                0,
                int((time.time() - stat_result.st_mtime) / 86400.0),
            )
            return {
                "path": str(path),
                "name": path.name,
                "size": stat_result.st_size,
                "age": age_days,
                "state": None,
                "kind": None,
                "confidence": CONFIDENCE_RULE,
                "reason": (
                    rule.get("note")
                    or f"Your rule: {rule.get('value', '')}"
                ),
            }

        for dirpath, dirnames, filenames in os.walk(
            root,
            onerror=lambda _error: None,
        ):
            if not self._running:
                break

            dirnames[:] = [
                name
                for name in dirnames
                if not self._should_prune_dir(dirpath, name)
            ]

            for fname in filenames:
                if not self._running:
                    break

                scanned += 1
                fpath = Path(dirpath) / fname

                try:
                    if not fpath.is_file():
                        continue

                    # Resolve symlinks before any classification.
                    if is_hard_protected_path(fpath):
                        continue

                    suffix = fpath.suffix.lower()

                    # A JAR stays protected unless it is structurally
                    # recognized as an old orphaned Minecraft mod.
                    if suffix == ".jar":
                        try:
                            stat_result = fpath.stat()
                            age_days = (
                                time.time() - stat_result.st_mtime
                            ) / 86400.0

                            if (
                                age_days >= ORPHAN_MIN_AGE_DAYS
                                and is_orphan_mod(fpath)
                            ):
                                kind, _preview = sniff_file_kind(fpath)
                                if not is_hard_protected_file(
                                    fpath,
                                    allow_orphan_jar=True,
                                    kind=kind,
                                ):
                                    state = extract_state(
                                        fpath,
                                        stat_result.st_size,
                                        age_days,
                                    )
                                    add_result({
                                        "path": str(fpath),
                                        "name": fpath.name,
                                        "size": stat_result.st_size,
                                        "age": int(age_days),
                                        "state": state,
                                        "kind": "minecraft-mod",
                                        "confidence": CONFIDENCE_RULE,
                                        "reason": (
                                            f"A mod you haven't used in "
                                            f"{int(age_days)} days — not loaded "
                                            "by any Minecraft instance"
                                        ),
                                    })
                        except (PermissionError, OSError, FileNotFoundError):
                            pass
                        continue

                    # VM disk files are never sent to generic AI classification.
                    # They are candidates only when the structural VM check
                    # positively identifies an old, unused image.
                    if suffix in VM_DISK_EXTS:
                        if is_vm_leftover(fpath):
                            stat_result = fpath.stat()
                            age_days = (
                                time.time() - stat_result.st_mtime
                            ) / 86400.0
                            state = extract_state(
                                fpath,
                                stat_result.st_size,
                                age_days,
                            )
                            add_result({
                                "path": str(fpath),
                                "name": fpath.name,
                                "size": stat_result.st_size,
                                "age": int(age_days),
                                "state": state,
                                "kind": "vm-leftover",
                                "confidence": CONFIDENCE_RULE,
                                "reason": (
                                    f"An old virtual-machine file "
                                    f"({int(age_days)} days) — no launcher "
                                    "or VM still uses it"
                                ),
                            })
                        continue

                    # Immutable protections always win over user rules and AI.
                    if is_dpkg_owned(fpath):
                        continue

                    kind, _preview = sniff_file_kind(fpath)
                    if is_hard_protected_file(fpath, kind=kind):
                        continue
                    if kind in PROTECTED_KINDS:
                        continue

                    rule_action, rule = self.rules.match(fpath)
                    if rule_action == "protect":
                        continue

                    stat_result = fpath.stat()
                    size = stat_result.st_size
                    age_days = (
                        time.time() - stat_result.st_mtime
                    ) / 86400.0
                    state = extract_state(fpath, size, age_days)

                    if rule_action == "flag":
                        add_result(make_rule_result(fpath, stat_result, rule))
                        continue

                    if (
                        screenshot_age_days > 0
                        and is_screenshot(fpath)
                        and age_days > screenshot_age_days
                    ):
                        add_result({
                            "path": str(fpath),
                            "name": fpath.name,
                            "size": size,
                            "age": int(age_days),
                            "state": state,
                            "kind": kind,
                            "confidence": CONFIDENCE_RULE,
                            "reason": (
                                f"An old screenshot ({int(age_days)} days) "
                                "— probably no longer needed"
                            ),
                        })
                        continue

                    # Actual Q-learning inference: one policy decision for
                    # this eligible file, without exploratory randomness.
                    if self.agent.act(state, explore=False) != 1:
                        continue

                    conf = self.agent.confidence(state)
                    if manual < 0:
                        key = (state[0], state[3])
                        if key not in threshold_cache:
                            threshold_cache[key] = (
                                self.agent.dynamic_threshold(state=state)
                            )
                        threshold = threshold_cache[key]
                    else:
                        threshold = min_confidence

                    if threshold > 0 and conf < threshold:
                        continue

                    add_result({
                        "path": str(fpath),
                        "name": fpath.name,
                        "size": size,
                        "age": int(age_days),
                        "state": state,
                        "kind": kind,
                        "confidence": conf,
                        "reason": plain_reason(fpath, size, int(age_days)),
                    })

                except (PermissionError, OSError, FileNotFoundError, RuntimeError):
                    continue
                finally:
                    now = time.time()
                    flush_batch()

                    if now - last_emit >= BATCH_MIN_SECONDS:
                        # No preliminary counting pass: progress is live and
                        # the indeterminate bar avoids an expensive second walk.
                        self.progress.emit(
                            scanned,
                            0,
                            str(dirpath),
                            -1.0,
                            False,
                        )
                        last_emit = now

        flush_batch(force=True)
        self.progress.emit(scanned, 0, "", -1.0, False)
        self.finished_scan.emit(results)
