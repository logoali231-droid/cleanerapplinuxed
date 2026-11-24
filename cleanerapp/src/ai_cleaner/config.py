"""Paths, constants, and per-user config directory."""

import os
from turtle import home

# Sentinels for confidence values that come from rules/screenshots, not the AI.
# The AI's real confidence range is roughly 0–30, so anything over 100 is a
# rule-derived value and should never be used for calibration.
CONFIDENCE_RULE = 999.0
CONFIDENCE_RULE_THRESHOLD = 900.0


def _user_home():
    """Resolve the real user's home even when we're running as root."""
    if os.geteuid() == 0:
        env_home = os.environ.get("AI_CLEANER_USER_HOME")
        if env_home and os.path.isdir(env_home):
            return env_home
        for var in ("SUDO_USER", "PKEXEC_USER", "USER"):
            u = os.environ.get(var)
            if u and u != "root":
                for home in (f"/home/{u}", f"/Users/{u}"):
                    if os.path.isdir(home):
                        return home
    return os.path.expanduser("~")


CONFIG_DIR = os.path.join(home, ".config", "ai_file_cleaner")
QTABLE_PATH = os.path.join(CONFIG_DIR, "qtable.json")
RULES_PATH = os.path.join(CONFIG_DIR, "rules.json")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")
DEFAULTS_SEEDED_FLAG = os.path.join(CONFIG_DIR, ".defaults_seeded")
DECISIONS_PATH = os.path.join(CONFIG_DIR, "decisions.jsonl")
ACTION_LOG_PATH = os.path.join(CONFIG_DIR, "actions.jsonl")  # NOVO
DRY_RUN = True  # NOVO — o __main__ desliga com --apply

HOME = _user_home()
IS_ROOT = os.geteuid() == 0


def fix_user_ownership(path):
    """
    Preserve the normal user's ownership when the app runs as root.
    """
    if not IS_ROOT:
        return

    try:
        owner = os.stat(HOME)
        os.chown(
            path,
            owner.st_uid,
            owner.st_gid,
            follow_symlinks=False,
        )
    except (OSError, TypeError):
        pass


try:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    fix_user_ownership(CONFIG_DIR)
except OSError:
    pass
