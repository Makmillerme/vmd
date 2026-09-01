#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Головний скрипт запуску VMD Extractor
Автоматично налаштовує середовище та запускає процес завантаження та парсингу
"""

import os
import sys
import subprocess
from pathlib import Path

def check_and_setup_venv():
    """Перевірка та налаштування віртуального середовища"""
    venv_path = Path("venv")
    venv_python = venv_path / "Scripts" / "python.exe" if sys.platform == "win32" else venv_path / "bin" / "python"
    
    # Перевіряємо чи існує venv
    if not venv_path.exists() or not venv_python.exists():
        print("="*60)
        print("Віртуальне середовище не знайдено!")
        print("="*60)
        print("Створюємо віртуальне середовище...")
        
        # Створюємо venv
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
        print("✓ Віртуальне середовище створено")
        
        # Встановлюємо залежності
        print("\nВстановлюємо залежності...")
        pip_path = venv_path / "Scripts" / "pip.exe" if sys.platform == "win32" else venv_path / "bin" / "pip"
        subprocess.run([str(pip_path), "install", "-r", "requirements.txt"], check=True)
        print("✓ Залежності встановлено")
        print("="*60)
        print()
    
    return venv_python

def is_env_configured() -> bool:
    """True if .env file exists or Docker/compose already injected credentials."""
    if Path(".env").exists():
        return True
    return bool(os.environ.get("IMAP_USER") and os.environ.get("IMAP_PASS"))


def check_env_file():
    """Перевірка наявності .env файлу або змінних середовища (Docker env_file)."""
    if is_env_configured():
        return

    print("=" * 60)
    print("УВАГА: Файл .env не знайдено і IMAP_* не задані в середовищі!")
    print("=" * 60)
    print("Створіть файл .env в корені проекту або задайте IMAP_USER/IMAP_PASS.")
    print("=" * 60)
    print()

    if not sys.stdin.isatty():
        print("Завершено (неінтерактивний режим, напр. Docker).")
        sys.exit(1)

    response = input("Продовжити без .env файлу? (y/n): ").strip().lower()
    if response != "y":
        print("Завершено. Створіть .env файл та запустіть скрипт знову.")
        sys.exit(1)


def get_runtime_python() -> Path:
    """Python для запуску extractor: venv локально, system python у Docker."""
    if os.environ.get("VMD_DOCKER") == "1":
        return Path(sys.executable)
    return check_and_setup_venv()

def main():
    """Головна функція"""
    # Перевірка .env файлу
    check_env_file()
    
    # Налаштування venv
    venv_python = get_runtime_python()
    
    # Якщо є аргументи командного рядка - запускаємо extractor напряму
    if len(sys.argv) > 1:
        extractor_script = Path("vmd_extractor") / "cli" / "extractor.py"
        
        if not extractor_script.exists():
            print(f"Помилка: Файл {extractor_script} не знайдено!")
            sys.exit(1)
        
        # Запускаємо extractor через venv Python з передачею всіх аргументів
        try:
            result = subprocess.run(
                [str(venv_python), str(extractor_script)] + sys.argv[1:],
                check=False
            )
            sys.exit(result.returncode)
        except KeyboardInterrupt:
            print("\n\nОперацію скасовано користувачем")
            sys.exit(1)
        except Exception as e:
            print(f"\n\nПомилка запуску: {e}")
            sys.exit(1)
    else:
        # Якщо немає аргументів - запускаємо інтерактивне меню
        menu_script = Path("vmd_extractor") / "cli" / "menu.py"
        
        if not menu_script.exists():
            print(f"Помилка: Файл {menu_script} не знайдено!")
            sys.exit(1)
        
        try:
            result = subprocess.run(
                [str(venv_python), str(menu_script)],
                check=False
            )
            sys.exit(result.returncode)
        except KeyboardInterrupt:
            print("\n\nОперацію скасовано користувачем")
            sys.exit(1)
        except Exception as e:
            print(f"\n\nПомилка запуску: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()

