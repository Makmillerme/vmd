#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Меню та операції з базою даних.
Рефакторено на повний async для сумісності з main menu.
"""

import sqlite3
from collections import Counter
from datetime import date, timedelta
from typing import List, Dict, Optional

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.config import DB_PATH, LOG_PATH

from .base import BaseMenu
from .utils import (
    clear_screen, print_header, print_menu, wait_for_enter, get_user_choice,
    _to_int, _to_float, _clean_text, _parse_date, _safe_load_payload,
    _match_substring, _prompt_optional, _prompt_number
)


def _normalize_model_name(model: str) -> str:
    model = (model or "").strip()
    if not model:
        return ""
    parts = []
    for token in model.split():
        if any(ch.isalpha() for ch in token):
            cleaned = "".join(ch for ch in token if ch.isalpha())
            if cleaned:
                parts.append(cleaned.upper())
    return " ".join(parts) or model.strip()


def _load_vehicle_rows(cursor) -> List[Dict]:
    """Завантажує vehicles з БД, використовуючи прямі колонки (нова структура)"""
    cursor.execute("""
        SELECT id, mrn, vin, brand, model, vehicle_type, year_calendar, 
               customs_value, create_at_ccd, created_at, payload_json 
        FROM vehicles 
        ORDER BY created_at DESC
    """)
    records = []
    for row in cursor.fetchall():
        create_date = _parse_date(_clean_text(row["create_at_ccd"]) or _clean_text(row["created_at"]))
        payload = _safe_load_payload(row["payload_json"])
        records.append({
            "id": row["id"],
            "mrn": _clean_text(row["mrn"]),
            "vin": _clean_text(row["vin"]),
            "brand": _clean_text(row["brand"]),
            "model": _clean_text(row["model"]),
            "year_calendar": _to_int(row["year_calendar"]),
            "customs_value": _to_float(row["customs_value"]),
            "vehicle_type": _clean_text(row["vehicle_type"]),
            "ccd_date": create_date,
            "payload": payload,
        })
    return records


class DatabaseMenu(BaseMenu):
    """Меню управління базою даних"""
    
    async def show_db_stats(self) -> None:
        """Показати статистику БД"""
        print_header("СТАТИСТИКА БАЗИ ДАНИХ")
        
        try:
            async with self.db_context() as db:
                conn = sqlite3.connect(db.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                vehicles = _load_vehicle_rows(cursor)

                if not vehicles:
                    print("  У таблиці vehicles немає записів.")
                    conn.close()
                    return

                total_vehicles = len(vehicles)
                valid_vehicles = sum(1 for v in vehicles if v["vehicle_type"])

                brand_model_counter = Counter()
                for vehicle in vehicles:
                    brand = vehicle["brand"] or "Невідома марка"
                    base_model = _normalize_model_name(vehicle["model"])
                    if not base_model:
                        base_model = vehicle["model"] or "Невідома модель"
                    key = (brand, base_model)
                    brand_model_counter[key] += 1

                today = date.today()
                current_week_start = today - timedelta(days=today.weekday())
                previous_week_start = current_week_start - timedelta(days=7)
                previous_week_end = current_week_start - timedelta(days=1)
                current_month_start = date(today.year, today.month, 1)
                previous_month_end = current_month_start - timedelta(days=1)
                previous_month_start = date(previous_month_end.year, previous_month_end.month, 1)

                def count_in_range(start: date, end: date) -> int:
                    return sum(
                        1
                        for v in vehicles
                        if v["ccd_date"] and start <= v["ccd_date"] <= end
                    )

                current_week_count = count_in_range(current_week_start, today)
                previous_week_count = count_in_range(previous_week_start, previous_week_end)
                current_month_count = count_in_range(current_month_start, today)
                previous_month_count = count_in_range(previous_month_start, previous_month_end)

                def format_range(start: date, end: date) -> str:
                    return f"{start.strftime('%d.%m.%Y')} - {end.strftime('%d.%m.%Y')}"

                non_vehicle_count = total_vehicles - valid_vehicles

                print("  Загальна статистика по vehicles:\n")
                print(f"     Загальна кількість транспорту в таблиці: {valid_vehicles}")
                print(f"     Загальна кількість записів в таблиці: {total_vehicles}")
                print(f"     Інше (не транспорт): {non_vehicle_count}")

                print("\n  ВМД за періоди:")
                print(f"     Поточний тиждень ({format_range(current_week_start, today)}): {current_week_count}")
                print(f"     Попередній тиждень ({format_range(previous_week_start, previous_week_end)}): {previous_week_count}")
                print(f"     Поточний місяць ({format_range(current_month_start, today)}): {current_month_count}")
                print(f"     Попередній місяць ({format_range(previous_month_start, previous_month_end)}): {previous_month_count}")

                print("\n  Марки / моделі (топ-10):")
                for (brand, model), count in brand_model_counter.most_common(10):
                    print(f"     {brand} {model}: {count}")

                cursor.execute("SELECT started_at, status, files_downloaded FROM sync_runs ORDER BY id DESC LIMIT 1")
                last_sync = cursor.fetchone()
                if last_sync:
                    print(f"\n  Остання синхронізація:")
                    print(f"     Дата: {last_sync[0]}")
                    print(f"     Статус: {last_sync[1]}")
                    print(f"     Файлів завантажено: {last_sync[2]}")

                conn.close()
        except Exception as e:
            print(f"  Помилка при отриманні статистики: {e}")
        
        print()

    async def search_vehicles(self) -> None:
        """Пошук транспортних засобів за VIN/MRN"""
        print_header("ПОШУК ТРАНСПОРТНИХ ЗАСОБІВ")
        print("  Оберіть за яким полем виконати пошук:\n")
        search_options = {
            "1": "VIN / SN",
            "2": "MRN",
            "0": "Повернутися назад"
        }
        for key, label in search_options.items():
            print(f"  {key}. {label}")
        print()

        choice = get_user_choice(search_options)

        vin_filter: Optional[str] = None
        mrn_filter: Optional[str] = None

        if choice == "0":
            return

        if choice == "1":
            vin_filter = _prompt_optional("  Введіть VIN / SN: ")
            if not vin_filter:
                print("  Значення VIN / SN не вказано. Пошук скасовано.")
                return

        if choice == "2":
            mrn_filter = _prompt_optional("  Введіть MRN: ")
            if not mrn_filter:
                print("  Значення MRN не вказано. Пошук скасовано.")
                return

        async with self.db_context() as db:
            conn = sqlite3.connect(db.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            try:
                vehicles = _load_vehicle_rows(cursor)
            finally:
                conn.close()

        matches = []
        for vehicle in vehicles:
            vehicle_type = vehicle["vehicle_type"]
            if not vehicle_type:
                continue

            vin_value = vehicle["vin"]
            mrn_value = vehicle["mrn"]

            if vin_filter:
                if not vin_value or not _match_substring(vin_value, vin_filter):
                    continue
            if mrn_filter:
                if not mrn_value or not _match_substring(mrn_value, mrn_filter):
                    continue

            matches.append(vehicle)
            if len(matches) >= 50:
                break

        if not matches:
            print("\n  Нічого не знайдено за заданими умовами.")
            return

        print(f"\n  Знайдено {len(matches)} записів (показано до 50).\n")
        print("  № | MRN | Марка / Модель | Рік | Вартість | VIN / SN")
        print("  " + "-" * 80)

        for idx, vehicle in enumerate(matches, start=1):
            mrn = vehicle["mrn"] or "-"
            brand = vehicle["brand"] or "-"
            model = vehicle["model"] or "-"
            year = vehicle["year_calendar"] if vehicle["year_calendar"] is not None else "-"
            value = vehicle["customs_value"] if vehicle["customs_value"] is not None else 0
            vin = vehicle["vin"] or "-"
            print(f"  {idx:>2} | {mrn} | {brand} {model} | {year} | {value:,.0f} | {vin}")

    async def filter_vehicles(self) -> None:
        """Фільтр транспортних засобів із незалежними параметрами та пагінацією"""
        print_header("ФІЛЬТР ТРАНСПОРТНИХ ЗАСОБІВ")
        print("  Залишайте поле порожнім, якщо не хочете застосовувати фільтр.\n")

        async with self.db_context() as db:
            conn = sqlite3.connect(db.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            try:
                vehicles = _load_vehicle_rows(cursor)
            finally:
                conn.close()

        if not vehicles:
            print("  У таблиці vehicles немає записів.")
            return

        vehicle_types = sorted({v["vehicle_type"] for v in vehicles if v["vehicle_type"]})

        vehicle_type_filter = None
        if vehicle_types:
            print("  Доступні типи транспорту:")
            for idx, vtype in enumerate(vehicle_types, start=1):
                print(f"     {idx}. {vtype}")
            any_option = len(vehicle_types) + 1
            print(f"     {any_option}. Будь-який")
            print("     0. Повернутися назад")

            while True:
                choice = input("  Ваш вибір (номер або Enter): ").strip()
                if not choice:
                    break
                if choice == "0":
                    return
                if choice.isdigit():
                    idx = int(choice)
                    if 1 <= idx <= len(vehicle_types):
                        vehicle_type_filter = vehicle_types[idx - 1]
                        break
                    if idx == any_option:
                        break
                print("  Невірний вибір. Спробуйте ще раз.")

        brand_filter = _prompt_optional("\n  Марка: ")
        model_filter = _prompt_optional("  Модель: ")

        print("\n  Діапазон року випуску (year_calendar)")
        year_from = _prompt_number("    Від (наприклад, 2015): ", int)
        year_to = _prompt_number("    До (наприклад, 2024): ", int)

        print("\n  Діапазон митної вартості (в грн)")
        value_from = _prompt_number("    Від: ", float)
        value_to = _prompt_number("    До: ", float)

        filtered: List[Dict] = []

        for vehicle in vehicles:
            if not vehicle["vehicle_type"]:
                continue

            brand_value = vehicle["brand"]
            model_value = vehicle["model"]
            year_value = vehicle["year_calendar"]
            customs_value = vehicle["customs_value"]

            if vehicle_type_filter and vehicle["vehicle_type"] != vehicle_type_filter:
                continue
            if brand_filter and (not brand_value or not _match_substring(brand_value, brand_filter)):
                continue
            if model_filter and (not model_value or not _match_substring(model_value, model_filter)):
                continue
            if year_from is not None:
                if year_value is None or year_value < year_from:
                    continue
            if year_to is not None:
                if year_value is None or year_value > year_to:
                    continue
            if value_from is not None:
                if customs_value is None or customs_value < value_from:
                    continue
            if value_to is not None:
                if customs_value is None or customs_value > value_to:
                    continue

            filtered.append(vehicle)

        if not filtered:
            print("\n  Нічого не знайдено за заданими умовами.")
            return

        total = len(filtered)
        page_size = 20
        page = 0

        while True:
            start = page * page_size
            end = start + page_size
            page_rows = filtered[start:end]

            if not page_rows:
                print("\n  Дані відсутні на цій сторінці.")
            else:
                print(f"\n  Показано {start + 1}-{start + len(page_rows)} з {total} записів.\n")
                print("  № | MRN | Марка / Модель | Рік | Вартість | VIN / SN")
                print("  " + "-" * 80)

                for idx, vehicle in enumerate(page_rows, start=start + 1):
                    mrn = vehicle["mrn"] or "-"
                    brand = vehicle["brand"] or "-"
                    model = vehicle["model"] or "-"
                    year = vehicle["year_calendar"] if vehicle["year_calendar"] is not None else "-"
                    value = vehicle["customs_value"] if vehicle["customs_value"] is not None else 0
                    vin = vehicle["vin"] or "-"
                    print(f"  {idx:>2} | {mrn} | {brand} {model} | {year} | {value:,.0f} | {vin}")

            if total <= page_size:
                break

            print("\n  Команди: [N]аступна сторінка, [P]опередня сторінка, [Q] - повернутися")
            cmd = input("  Ваш вибір: ").strip().lower()

            if cmd == "n":
                if end >= total:
                    print("  Це остання сторінка.")
                else:
                    page += 1
            elif cmd == "p":
                if page == 0:
                    print("  Це перша сторінка.")
                else:
                    page -= 1
            elif cmd == "q":
                break
            else:
                print("  Невідома команда.")

    def show_logs(self) -> None:
        """Показати останні 30 логів"""
        print_header("ПЕРЕГЛЯД ЛОГІВ")
        
        if not LOG_PATH.exists():
            print("  Лог-файл не знайдено.")
            print(f"  Очікуваний шлях: {LOG_PATH}")
            return
        
        try:
            with open(LOG_PATH, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            last_lines = lines[-30:] if len(lines) > 30 else lines
            
            if not last_lines:
                print("  Лог-файл порожній.")
                return
            
            print(f"  Показано останні {len(last_lines)} записів з {len(lines)} загалом\n")
            print("=" * 80)
            
            for line in last_lines:
                line = line.rstrip()
                if line:
                    print(f"  {line}")
            
            print("=" * 80)
            print(f"\n  Повний шлях до лог-файлу: {LOG_PATH}")
            
        except Exception as e:
            print(f"  Помилка при читанні лог-файлу: {e}")

    async def run(self) -> None:
        """Головне меню управління БД"""
        options = {
            "1": "Показати статистику БД",
            "2": "Пошук транспортних засобів",
            "3": "Фільтр транспортних засобів",
            "4": "Перегляд логів",
            "0": "Повернутися до головного меню"
        }
        
        handlers = {
            "1": self.show_db_stats,
            "2": self.search_vehicles,
            "3": self.filter_vehicles,
            "4": lambda: self.show_logs(),  # sync function wrapped
        }
        
        await self.run_menu_loop(options, handlers, "УПРАВЛІННЯ БАЗОЮ ДАНИХ")


# Backward compatibility
async def show_db_menu():
    """Меню управління БД (backward compatibility)"""
    menu = DatabaseMenu()
    await menu.run()


async def show_db_stats():
    """Показати статистику БД (backward compatibility)"""
    menu = DatabaseMenu()
    await menu.show_db_stats()


async def search_vehicles():
    """Пошук транспортних засобів (backward compatibility)"""
    menu = DatabaseMenu()
    await menu.search_vehicles()


async def filter_vehicles():
    """Фільтр транспортних засобів (backward compatibility)"""
    menu = DatabaseMenu()
    await menu.filter_vehicles()
