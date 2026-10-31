#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# PhoneSurgeon — Advanced ADB Toolkit Launcher
# ─────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
G='\033[92m'  R='\033[91m'  C='\033[96m'  B='\033[1m'  X='\033[0m'

echo ""
echo -e "${C}${B}"
echo "    ╔══════════════════════════════════════════════╗"
echo "    ║   PhoneSurgeon - Advanced ADB Toolkit        ║"
echo "    ╚══════════════════════════════════════════════╝"
echo -e "${X}"

# Check Python 3
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo -e "  ${R}[ERROR] Python 3 is not installed!${X}"
    echo "  Install: sudo apt install python3  (or brew install python3)"
    exit 1
fi

VER=$($PYTHON --version 2>&1)
echo -e "  ${G}[OK]${X} $VER found"
echo -e "  ${C}[*]${X} Launching PhoneSurgeon..."
echo ""

exec $PYTHON "$SCRIPT_DIR/phonesurgeon.py" "$@"
