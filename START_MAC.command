#!/bin/bash
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
    python3 launch.py
    result=$?
    if [ "$result" -ne 0 ]; then
        read -r -p "The app could not start. Press Return to close."
    fi
    exit "$result"
fi
echo "Python 3.10 or newer is required. Install it from python.org, then open this file again."
read -r -p "Press Return to close."

