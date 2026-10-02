#!/usr/bin/env bash
# One-step environment setup for firestone-bot.
#
# Rebuilds the virtualenv in .venv and verifies every dependency the bot
# needs at import time (including the tesseract binary, which is not a
# pip package and can silently break after system package-manager
# upgrades/uninstalls). Safe to re-run after any system rebuild.
#
# Usage: ./setup.sh   (from the repository root)

set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"

echo "[setup] using interpreter: $PY ($($PY --version 2>&1))"
$PY -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "[setup] checking imports..."
.venv/bin/python - <<'EOF'
modules = ['cv2', 'mss', 'numpy', 'pyautogui', 'pynput', 'pytesseract', 'requests', 'watchdog', 'tkinter']
failed = []
for name in modules:
    try:
        __import__(name)
    except Exception as exc:  # pylint: disable=broad-except
        failed.append(f'{name}: {exc}')
if failed:
    print('[setup] import check FAILED:')
    for line in failed:
        print('  ', line)
    raise SystemExit(1)
print('[setup] all python imports OK')
EOF

echo "[setup] checking tesseract binary..."
if command -v tesseract >/dev/null 2>&1 && tesseract --version >/dev/null 2>&1; then
    echo "[setup] tesseract OK ($(tesseract --version 2>/dev/null | head -1))"
else
    echo "[setup] ERROR: tesseract binary is missing or broken (see messages above)."
    echo "        Install it, e.g.:  brew install tesseract"
    exit 1
fi

echo "[setup] done. Run the bot with:"
echo "        cd src && ../.venv/bin/python main.py"
