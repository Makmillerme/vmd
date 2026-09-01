#!/bin/bash
# VMD Extractor CLI - скрипт для запуску в Termux (Android)

# Визначаємо директорію скрипта
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Перевіряємо чи є venv
if [ -f "venv/bin/python" ]; then
    ./venv/bin/python run.py "$@"
elif [ -f "venv/bin/python3" ]; then
    ./venv/bin/python3 run.py "$@"
else
    python3 run.py "$@"
fi





