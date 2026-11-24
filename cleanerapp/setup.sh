
#!/usr/bin/env bash
# AI File Cleaner installer
# Linux Mint / Ubuntu

set -Eeuo pipefail

APP_ID="ai-file-cleaner"
APP_NAME="AI File Cleaner"

SCRIPT_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P
)"

PKG_SRC="$SCRIPT_DIR/src/ai_cleaner"

# --------------------------------------------------
# 1. Basic checks
# --------------------------------------------------

if [[ "$EUID" -eq 0 ]]; then
    echo "ERROR: Do not run this installer with sudo."
    echo "Run: ./setup.sh"
    exit 1
fi

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    echo "ERROR: A Python virtual environment is active."
    echo "Deactivate it first with: deactivate"
    exit 1
fi

if [[ ! -f "$PKG_SRC/__main__.py" ]]; then
    echo "ERROR: Python package not found:"
    echo "$PKG_SRC"
    exit 1
fi

PYTHON_BIN="/usr/bin/python3"

if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "$PYTHON_BIN" ]]; then
    echo "ERROR: Python 3 is not installed."
    exit 1
fi

if ! "$PYTHON_BIN" -c \
    'import sys; sys.exit(sys.version_info < (3, 8))'
then
    echo "ERROR: Python 3.8 or newer is required."
    exit 1
fi

# --------------------------------------------------
# 2. Dependencies
# --------------------------------------------------

echo "Checking dependencies..."

if ! "$PYTHON_BIN" -c "import PyQt5" >/dev/null 2>&1; then

    echo "PyQt5 is missing."

    if ! command -v apt-get >/dev/null 2>&1; then
        echo "ERROR: This installer requires an apt-based system."
        exit 1
    fi

    if ! command -v sudo >/dev/null 2>&1; then
        echo "ERROR: sudo is required to install dependencies."
        exit 1
    fi

    sudo apt-get update
    sudo apt-get install -y python3-pyqt5
fi

if ! "$PYTHON_BIN" -c "import PyQt5" >/dev/null 2>&1; then
    echo "ERROR: PyQt5 is still unavailable."
    exit 1
fi

# --------------------------------------------------
# 3. Installation paths
# --------------------------------------------------

BIN_DIR="$HOME/.local/bin"
SHARE_DIR="$HOME/.local/share"
APP_DIR="$SHARE_DIR/$APP_ID"

DESKTOP_DIR="$HOME/.local/share/applications"

ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p \
    "$BIN_DIR" \
    "$SHARE_DIR" \
    "$DESKTOP_DIR" \
    "$ICON_DIR"

# --------------------------------------------------
# 4. Prepare staged installation
# --------------------------------------------------

STAGE_DIR="$(
    mktemp -d "$SHARE_DIR/.${APP_ID}.stage.XXXXXX"
)"

BACKUP_DIR=""

cleanup() {

    if [[ -n "$STAGE_DIR" && -d "$STAGE_DIR" ]]; then
        rm -rf -- "$STAGE_DIR"
    fi

    # Restore previous installation if replacement failed.
    if [[ -n "$BACKUP_DIR" \
        && -d "$BACKUP_DIR" \
        && ! -e "$APP_DIR" ]]; then

        mv -- "$BACKUP_DIR" "$APP_DIR" || true
    fi
}

trap cleanup EXIT

echo "Preparing application..."

cp -a "$PKG_SRC" "$STAGE_DIR/ai_cleaner"

# Never install stale Python bytecode.
find "$STAGE_DIR" \
    -type d \
    -name "__pycache__" \
    -prune \
    -exec rm -rf {} +

find "$STAGE_DIR" \
    -type f \
    \( -name "*.pyc" -o -name "*.pyo" \) \
    -delete

# --------------------------------------------------
# 5. Test imports BEFORE replacing current version
# --------------------------------------------------

echo "Testing application imports..."

if ! env \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen \
    PYTHONPATH="$STAGE_DIR" \
    "$PYTHON_BIN" \
    -c "import ai_cleaner.config; import ai_cleaner.ui.wizard"
then
    echo ""
    echo "ERROR: Application import test failed."
    echo "The existing installation was not replaced."
    echo "Check the Python source files."
    exit 1
fi

# --------------------------------------------------
# 6. Replace old installation safely
# --------------------------------------------------

if [[ -e "$APP_DIR" ]]; then

    BACKUP_DIR="$(
        mktemp -d "$SHARE_DIR/.${APP_ID}.backup.XXXXXX"
    )"

    rmdir "$BACKUP_DIR"

    mv -- "$APP_DIR" "$BACKUP_DIR"
fi

if ! mv -- "$STAGE_DIR" "$APP_DIR"; then
    echo "ERROR: Could not activate new installation."
    exit 1
fi

STAGE_DIR=""

if [[ -n "$BACKUP_DIR" ]]; then
    rm -rf -- "$BACKUP_DIR"
    BACKUP_DIR=""
fi

# --------------------------------------------------
# 7. Launcher
# --------------------------------------------------

echo "Creating launcher..."

LAUNCHER_TMP="$BIN_DIR/.${APP_ID}.tmp.$$"

cat > "$LAUNCHER_TMP" <<EOF
#!/usr/bin/env bash

export PYTHONPATH="$APP_DIR:\${PYTHONPATH:-}"

exec "$PYTHON_BIN" -m ai_cleaner "\$@"
EOF

chmod 755 "$LAUNCHER_TMP"
mv -- "$LAUNCHER_TMP" "$BIN_DIR/$APP_ID"

# --------------------------------------------------
# 8. Application icon
# --------------------------------------------------

ICON_TMP="$ICON_DIR/.${APP_ID}.svg.tmp"

cat > "$ICON_TMP" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#4a9eff"/>
      <stop offset="1" stop-color="#2f7ad6"/>
    </linearGradient>
  </defs>

  <rect x="6" y="6" width="116" height="116"
        rx="26" fill="url(#g)"/>

  <path d="M40 34 L74 34 L88 48 L88 96 L40 96 Z"
        fill="#ffffff"/>

  <path d="M74 34 L74 48 L88 48 Z"
        fill="#cfdcf0"/>

  <line x1="50" y1="58" x2="78" y2="58"
        stroke="#cfdcf0" stroke-width="3"
        stroke-linecap="round"/>

  <line x1="50" y1="68" x2="78" y2="68"
        stroke="#cfdcf0" stroke-width="3"
        stroke-linecap="round"/>

  <line x1="50" y1="78" x2="70" y2="78"
        stroke="#cfdcf0" stroke-width="3"
        stroke-linecap="round"/>

  <path d="M94 22 L96.5 31 L105.5 33.5
           L96.5 36 L94 45 L91.5 36
           L82.5 33.5 L91.5 31 Z"
        fill="#ffd76a"/>
</svg>
SVG

chmod 644 "$ICON_TMP"
mv -- "$ICON_TMP" "$ICON_DIR/$APP_ID.svg"

# --------------------------------------------------
# 9. Desktop entry
# --------------------------------------------------

DESKTOP_TMP="$DESKTOP_DIR/.${APP_ID}.desktop.tmp"

cat > "$DESKTOP_TMP" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
GenericName=Disk Cleaner
Comment=Find and remove unused files safely
Exec="$BIN_DIR/$APP_ID"
Icon=$APP_ID
Terminal=false
Categories=Utility;System;FileTools;Qt;
Keywords=cleaner;disk;cleanup;ai;files;junk;space;
StartupNotify=true
StartupWMClass=ai-file-cleaner
EOF

chmod 644 "$DESKTOP_TMP"
mv -- "$DESKTOP_TMP" "$DESKTOP_DIR/$APP_ID.desktop"

# --------------------------------------------------
# 10. Refresh desktop caches
# --------------------------------------------------

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache \
        -f -t "$HOME/.local/share/icons/hicolor" \
        2>/dev/null || true
fi

# --------------------------------------------------
# 11. Done
# --------------------------------------------------

echo ""
echo "======================================"
echo " AI File Cleaner installed successfully"
echo "======================================"
echo ""

echo "Launch from your application menu:"
echo "  $APP_NAME"
echo ""

echo "Or run:"
echo "  $BIN_DIR/$APP_ID"
echo ""

echo "Installation:"
echo "  $APP_DIR"
echo ""

echo "User configuration:"
echo "  $HOME/.config/ai_file_cleaner"
echo ""

echo "Uninstall:"
echo "  rm -f \"$BIN_DIR/$APP_ID\""
echo "  rm -rf \"$APP_DIR\""
echo "  rm -f \"$DESKTOP_DIR/$APP_ID.desktop\""
echo "  rm -f \"$ICON_DIR/$APP_ID.svg\""
