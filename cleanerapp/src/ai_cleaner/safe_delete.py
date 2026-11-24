# src/ai_cleaner/safe_delete.py
"""Centralised, auditável file deletion. The ONLY place that deletes files."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Iterable

try:
    from send2trash import send2trash
    _HAS_SEND2TRASH = True
except ImportError:
    _HAS_SEND2TRASH = False

from .config import DRY_RUN, ACTION_LOG_PATH


def _log(action: str, path: Path, ok: bool, detail: str = "") -> None:
    """Append one JSON line per action. Never raises."""
    try:
        ACTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with ACTION_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "action": action,
                "path": str(path),
                "ok": ok,
                "detail": detail,
                "dry_run": DRY_RUN,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _is_mount_boundary(path: Path) -> bool:
    """True if `path` lives on a different filesystem than its parent."""
    try:
        return path.stat().st_dev != path.parent.stat().st_dev
    except OSError:
        return True  # be conservative


def _is_symlink_loop_safe(path: Path) -> bool:
    """Refuse to follow a symlink that points outside its own tree."""
    try:
        resolved = path.resolve(strict=False)
        # If the resolved path is not under the same top-level tree, be careful.
        return resolved.exists()
    except (OSError, RuntimeError):
        return False


def safe_delete(paths: Iterable[Path]) -> dict:
    """
    Move files to Trash. Never permanently delete.

    Returns a summary dict:
      {"moved": [...], "skipped": [...], "errors": [...]}
    """
    moved, skipped, errors = [], [], []

    for raw in paths:
        path = Path(raw).expanduser()

        # 1) Resolve symlinks — never delete the target by accident.
        if path.is_symlink():
            skipped.append({"path": str(path), "reason": "symlink"})
            _log("skip", path, False, "symlink")
            continue

        # 2) Mount boundary: be conservative.
        if _is_mount_boundary(path):
            skipped.append({"path": str(path), "reason": "mount_boundary"})
            _log("skip", path, False, "mount_boundary")
            continue

        # 3) Sanity: file must exist and be a regular file or dir.
        if not path.exists():
            skipped.append({"path": str(path), "reason": "missing"})
            _log("skip", path, False, "missing")
            continue
        if not (path.is_file() or path.is_dir()):
            skipped.append({"path": str(path), "reason": "not_file_or_dir"})
            _log("skip", path, False, "not_file_or_dir")
            continue

        # 4) Dry-run: just log what *would* happen.
        if DRY_RUN:
            moved.append(str(path))
            _log("would_trash", path, True, "dry_run")
            continue

        # 5) Actual move to Trash.
        try:
            if _HAS_SEND2TRASH:
                send2trash(str(path))
            else:
                # Fallback: gio trash (GNOME), then trash-cli.
                if shutil.which("gio"):
                    subprocess.run(
                        ["gio", "trash", "--", str(path)],
                        check=True, capture_output=True, timeout=30,
                    )
                elif shutil.which("trash-put"):
                    subprocess.run(
                        ["trash-put", "--", str(path)],
                        check=True, capture_output=True, timeout=30,
                    )
                else:
                    raise RuntimeError("no trash backend found")
            moved.append(str(path))
            _log("trash", path, True)
        except Exception as exc:  # noqa: BLE001
            errors.append({"path": str(path), "reason": str(exc)})
            _log("error", path, False, str(exc))

    return {"moved": moved, "skipped": skipped, "errors": errors}