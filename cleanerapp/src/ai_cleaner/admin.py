"""Admin relaunch: terminal / pkexec / askpass."""
import os
import sys
import shutil
import shlex
import tempfile
import subprocess
from datetime import datetime

from .config import HOME, CONFIG_DIR


def _admin_log(msg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(os.path.join(CONFIG_DIR, "admin-launch.log"), "a") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    except Exception:
        pass


def find_terminal():
    for t in ("mate-terminal", "x-terminal-emulator", "gnome-terminal",
              "xfce4-terminal", "konsole", "kitty", "alacritty", "xterm"):
        p = shutil.which(t)
        if p:
            return p
    return None


def find_askpass():
    for tool in ("zenity", "yad", "ssh-askpass", "ssh-askpass-gnome",
                 "ksshaskpass", "lxqt-openssh-askpass"):
        p = shutil.which(tool)
        if p:
            return p
    return None


def terminal_argv(term, script_path):
    name = os.path.basename(term)
    if name in ("gnome-terminal", "mate-terminal"):
        return [term, "--", "bash", script_path]
    if name == "xfce4-terminal":
        return [term, "--command", f"bash {shlex.quote(script_path)}"]
    if name == "konsole":
        return [term, "-e", "bash", script_path]
    return [term, "-e", "bash", script_path]


def _write_terminal_launcher(package_dir, folder, deep, signal_file):
    """
    Write a shell script to a temp file that:
      - cd's into the src/ dir (so `python3 -m ai_cleaner` works)
      - exports PYTHONPATH and the user's HOME
      - runs the app under sudo -E
    Returns the temp file path.
    """
    fd, tmp = tempfile.mkstemp(prefix="ai-cleaner-launch-", suffix=".sh")
    os.close(fd)

    inner = [f"sudo -E {shlex.quote(sys.executable or 'python3')}",
             "-m ai_cleaner --admin"]
    if folder:
        inner.append(f"--folder {shlex.quote(folder)}")
    if deep:
        inner.append("--deep")
    if signal_file:
        inner.append(f"--signal-file {shlex.quote(signal_file)}")
    cmd = " ".join(inner)

    script = f"""#!/bin/bash
echo '=== AI File Cleaner — admin launch ==='
echo 'The system will now ask for your password.'
echo
cd {shlex.quote(package_dir)}
export PYTHONPATH={shlex.quote(package_dir)}:$PYTHONPATH
export AI_CLEANER_USER_HOME={shlex.quote(HOME)}
{cmd}
rc=$?
echo
if [ $rc -ne 0 ]; then
    echo "=== Launch failed (exit $rc) ==="
    echo
    echo "If this is the first time, try again — the admin dialog may have"
    echo "timed out. If it keeps failing, check:"
    echo "  {CONFIG_DIR}/admin-launch.log"
fi
echo
echo 'Press Enter to close this window…'
read _
rm -f {shlex.quote(tmp)}
"""
    with open(tmp, "w") as f:
        f.write(script)
    os.chmod(tmp, 0o755)
    return tmp


def relaunch_as_admin(folder=None, deep=False, method="terminal",
                      signal_file=None, parent=None):
    python = sys.executable or "python3"
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    inner = [python, "-m", "ai_cleaner", "--admin"]
    if folder:      inner += ["--folder", folder]
    if deep:        inner += ["--deep"]
    if signal_file: inner += ["--signal-file", signal_file]

    _admin_log(f"method={method}  folder={folder}  deep={deep}")
    _admin_log(f"python={python}")
    _admin_log(f"package_dir={package_dir}")
    _admin_log(f"signal={signal_file}")

    if method == "terminal":
        term = find_terminal()
        if not term:
            return False, ("Couldn't find a terminal emulator.\n\n"
                           "Install one with:  sudo apt install mate-terminal")
        try:
            tmp = _write_terminal_launcher(package_dir, folder, deep, signal_file)
            argv = terminal_argv(term, tmp)
            _admin_log(f"exec: {argv}")
            subprocess.Popen(argv, close_fds=True)
            return True, ""
        except Exception as e:
            _admin_log(f"terminal Popen failed: {e}")
            return False, f"Couldn't launch {term}:\n\n{e}"

    if method == "askpass":
        askpass = find_askpass()
        if not askpass:
            return False, ("No graphical password tool found.\n\n"
                           "Install one with:  sudo apt install zenity\n"
                           "Or switch to Terminal.")
        env = os.environ.copy()
        env["SUDO_ASKPASS"] = askpass
        env["AI_CLEANER_USER_HOME"] = HOME
        env["PYTHONPATH"] = package_dir + os.pathsep + env.get("PYTHONPATH", "")
        try:
            _admin_log(f"askpass={askpass}")
            subprocess.Popen(["sudo", "-A", "-E"] + inner,
                             env=env, cwd=package_dir, close_fds=True)
            return True, ""
        except Exception as e:
            _admin_log(f"askpass failed: {e}")
            return False, f"Couldn't launch sudo with {askpass}:\n\n{e}"

    if method == "pkexec":
        pkexec = shutil.which("pkexec")
        if not pkexec:
            return False, ("pkexec isn't installed.\n\n"
                           "Switch the method to 'Terminal' and try again.")
        env_pairs = [
            f"HOME={os.environ.get('HOME','')}",
            f"DISPLAY={os.environ.get('DISPLAY', ':0')}",
            f"XAUTHORITY={os.environ.get('XAUTHORITY', os.path.expanduser('~/.Xauthority'))}",
            f"XDG_RUNTIME_DIR={os.environ.get('XDG_RUNTIME_DIR','')}",
            f"AI_CLEANER_USER_HOME={HOME}",
            f"PYTHONPATH={package_dir}",
            "QT_QPA_PLATFORM=xcb",
        ]
        argv = [pkexec, "env", "-C", package_dir] + env_pairs + inner
        try:
            _admin_log(f"exec: {argv}")
            subprocess.Popen(argv, close_fds=True)
            return True, ""
        except Exception as e:
            _admin_log(f"pkexec failed: {e}")
            return False, f"Couldn't launch pkexec:\n\n{e}"

    return False, f"Unknown method: {method}"
