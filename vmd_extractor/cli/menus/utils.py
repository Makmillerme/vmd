#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Утиліти для меню.
Винесені з cli/menu.py
"""

import os
import json
import calendar
from datetime import date, datetime, timedelta
from typing import Dict, Optional

def clear_screen():
    """Очищення екрану"""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header(title: str):
    """Виведення заголовка"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60 + "\n")


def print_menu(options: dict, title: str = "ВИБЕРІТЬ ОПЦІЮ"):
    """Виведення меню"""
    print_header(title)
    for key, value in options.items():
        print(f"  {key}. {value}")
    print()


def wait_for_enter(message: str = "\nНатисніть Enter для продовження..."):
    """Безпечне очікування натискання Enter з обробкою помилок"""
    try:
        input(message)
    except (EOFError, KeyboardInterrupt, OSError):
        # stdin закритий або перерваний - просто продовжуємо
        print()  # Додаємо новий рядок для коректного форматування
        pass


def get_user_choice(options: dict) -> str:
    """Отримання вибору користувача"""
    while True:
        try:
            choice = input("Ваш вибір: ").strip()
            if choice in options:
                return choice
            print(f"Помилка: невірний вибір. Оберіть один з: {', '.join(options.keys())}")
        except (EOFError, KeyboardInterrupt):
            # Якщо stdin закритий, повертаємо "0" для виходу
            print("\nПереривання вводу. Повертаємось до меню...")
            return "0"


def parse_date_input(date_str: str) -> date:
    """Парсинг дати з формату DD.MM.YYYY"""
    try:
        return datetime.strptime(date_str.strip(), "%d.%m.%Y").date()
    except ValueError:
        raise ValueError(f"Невірний формат дати: {date_str}. Використовуйте DD.MM.YYYY (наприклад, 01.08.2025)")


def get_date_input(prompt: str) -> date:
    """Отримання дати від користувача"""
    while True:
        try:
            date_str = input(f"{prompt} (формат: DD.MM.YYYY): ").strip()
            return parse_date_input(date_str)
        except ValueError as e:
            print(f"Помилка: {e}")
        except (EOFError, KeyboardInterrupt):
            # Якщо stdin закритий, викидаємо помилку для обробки вище
            raise


def get_date_input_optional(
    prompt: str,
    default_if_empty: Optional[date] = None,
) -> Optional[date]:
    """
    Отримання дати від користувача; порожній ввід повертає default_if_empty.
    """
    while True:
        try:
            date_str = input(f"{prompt}: ").strip()
            if not date_str:
                return default_if_empty
            return parse_date_input(date_str)
        except ValueError as e:
            print(f"Помилка: {e}")
        except (EOFError, KeyboardInterrupt):
            raise


def _prompt_optional(prompt_text: str) -> Optional[str]:
    """Зчитує рядок, повертає None якщо порожньо"""
    value = input(prompt_text).strip()
    return value or None


def _prompt_number(prompt_text: str, value_type=float) -> Optional[float]:
    """Зчитує число (int/float). Повертає None якщо порожньо або помилка"""
    value = input(prompt_text).strip()
    if not value:
        return None
    try:
        return value_type(value)
    except ValueError:
        print("   Невірний формат, значення буде проігноровано.")
        return None


def _safe_load_payload(payload_raw: Optional[str]) -> Dict:
    if not payload_raw:
        return {}
    try:
        return json.loads(payload_raw)
    except Exception:
        return {}


def _clean_text(value: Optional[str]) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _match_substring(value: str, pattern: str) -> bool:
    return pattern.lower() in value.lower()


def _to_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        # Пробуємо ISO формат YYYY-MM-DD
        return date.fromisoformat(value[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None


def get_current_week_range():
    """Повертає дати початку та кінця поточного тижня (понеділок - неділя)"""
    today = datetime.now().date()
    # Понеділок поточного тижня
    start_of_week = today - timedelta(days=today.weekday())
    # Неділя поточного тижня
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week.isoformat(), end_of_week.isoformat()


def get_current_month_range():
    """Повертає дати початку та кінця поточного місяця"""
    today = datetime.now().date()
    start_of_month = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    end_of_month = today.replace(day=last_day)
    return start_of_month.isoformat(), end_of_month.isoformat()


def get_current_quarter_range():
    """Повертає дати початку та кінця поточного кварталу"""
    today = datetime.now().date()
    current_quarter = (today.month - 1) // 3 + 1
    
    # Перший місяць кварталу
    first_month = (current_quarter - 1) * 3 + 1
    start_of_quarter = today.replace(month=first_month, day=1)
    
    # Останній місяць кварталу
    last_month = current_quarter * 3
    last_day = calendar.monthrange(today.year, last_month)[1]
    end_of_quarter = today.replace(month=last_month, day=last_day)
    
    return start_of_quarter.isoformat(), end_of_quarter.isoformat()


def get_previous_week_range():
    """Повертає дати початку та кінця попереднього тижня"""
    today = datetime.now().date()
    # Понеділок поточного тижня
    start_of_current_week = today - timedelta(days=today.weekday())
    # Понеділок попереднього тижня
    start_of_prev_week = start_of_current_week - timedelta(days=7)
    # Неділя попереднього тижня
    end_of_prev_week = start_of_prev_week + timedelta(days=6)
    return start_of_prev_week.isoformat(), end_of_prev_week.isoformat()


def get_previous_month_range():
    """Повертає дати початку та кінця попереднього місяця"""
    today = datetime.now().date()
    
    # Перший день попереднього місяця
    if today.month == 1:
        start_of_prev_month = today.replace(year=today.year - 1, month=12, day=1)
    else:
        start_of_prev_month = today.replace(month=today.month - 1, day=1)
    
    # Останній день попереднього місяця
    last_day = calendar.monthrange(start_of_prev_month.year, start_of_prev_month.month)[1]
    end_of_prev_month = start_of_prev_month.replace(day=last_day)
    
    return start_of_prev_month.isoformat(), end_of_prev_month.isoformat()


def format_date_range_ua(date_from: str, date_to: str) -> str:
    """Форматує діапазон дат в українському форматі"""
    MONTHS_UA = {
        1: "січня", 2: "лютого", 3: "березня", 4: "квітня",
        5: "травня", 6: "червня", 7: "липня", 8: "серпня",
        9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня"
    }
    
    try:
        d_from = datetime.strptime(date_from, "%Y-%m-%d")
        d_to = datetime.strptime(date_to, "%Y-%m-%d")
        
        from_str = f"{d_from.day} {MONTHS_UA[d_from.month]} {d_from.year}"
        to_str = f"{d_to.day} {MONTHS_UA[d_to.month]} {d_to.year}"
        
        return f"{from_str} - {to_str}"
    except Exception:
        return f"{date_from} - {date_to}"
