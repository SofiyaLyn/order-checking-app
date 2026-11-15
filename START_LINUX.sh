#!/bin/sh
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
    exec python3 launch.py
fi
echo "Python 3.10 or newer is required."
exit 1

