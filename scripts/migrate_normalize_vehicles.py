#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт міграції БД: Нормалізація таблиці vehicles

Додає нормалізовані колонки та заповнює їх з payload_json.
"""

import sqlite3
import json
import sys
import codecs
from pathlib import Path

# Виправляємо кодування для Windows
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Шлях до БД
DB_PATH = Path(__file__).parent.parent / "vmd_extractor" / "data" / "db" / "vmd_data.sqlite3"

# Нові колонки для додавання
NEW_COLUMNS = [
    ("vehicle_type", "TEXT"),
    ("brand", "TEXT"),
    ("uktzed", "TEXT"),
    ("description", "TEXT"),
    ("producer_country", "TEXT"),
    ("gross_weight", "TEXT"),
    ("net_weight", "TEXT"),
    ("gross_weight_kg", "INTEGER"),
    ("net_weight_kg", "INTEGER"),
    ("payload_kg", "INTEGER"),
    ("engine_cm3", "INTEGER"),
    ("seats", "INTEGER"),
    ("power_kw", "REAL"),
    ("wheel_formula", "TEXT"),
    ("year_model", "INTEGER"),
    ("year_calendar", "INTEGER"),
    ("quantity", "REAL"),
    ("serial_number", "TEXT"),
    ("unit_human", "TEXT"),
]


def get_existing_columns(cursor, table_name: str) -> set:
    """Отримує список існуючих колонок таблиці"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def add_columns(conn, cursor):
    """Додає нові колонки до таблиці vehicles"""
    existing = get_existing_columns(cursor, "vehicles")
    
    added = []
    skipped = []
    
    for col_name, col_type in NEW_COLUMNS:
        if col_name in existing:
            skipped.append(col_name)
        else:
            try:
                cursor.execute(f"ALTER TABLE vehicles ADD COLUMN {col_name} {col_type}")
                added.append(col_name)
            except sqlite3.OperationalError as e:
                print(f"  ⚠️ Помилка додавання {col_name}: {e}")
    
    conn.commit()
    
    if added:
        print(f"  ✅ Додано колонок: {len(added)}")
        for col in added:
            print(f"     - {col}")
    
    if skipped:
        print(f"  ℹ️ Вже існують: {len(skipped)}")
    
    return added


def populate_columns(conn, cursor):
    """Заповнює нові колонки з payload_json"""
    
    # Отримуємо всі записи з payload_json
    cursor.execute("SELECT id, payload_json FROM vehicles WHERE payload_json IS NOT NULL")
    rows = cursor.fetchall()
    
    print(f"  📊 Знайдено записів для міграції: {len(rows)}")
    
    updated = 0
    errors = 0
    
    for row_id, payload_json in rows:
        try:
            payload = json.loads(payload_json) if payload_json else {}
            
            # Підготовка значень
            vehicle_type = (payload.get("vehicle_type") or "").strip() or None
            brand = (payload.get("brand") or "").strip() or None
            uktzed = (payload.get("uktzed") or "").strip() or None
            description = (payload.get("description") or "").strip() or None
            producer_country = (payload.get("producer_country") or "").strip() or None
            gross_weight = (payload.get("gross_weight") or "").strip() if payload.get("gross_weight") else None
            net_weight = (payload.get("net_weight") or "").strip() if payload.get("net_weight") else None
            wheel_formula = (payload.get("wheel_formula") or "").strip() or None
            serial_number = (payload.get("serial_number") or "").strip() or None
            unit_human = (payload.get("unit_human") or "").strip() or None
            
            # Числові значення
            gross_weight_kg = None
            if payload.get("gross_weight_kg"):
                try:
                    gross_weight_kg = int(float(payload["gross_weight_kg"]))
                except (ValueError, TypeError):
                    pass
            
            net_weight_kg = None
            if payload.get("net_weight_kg"):
                try:
                    net_weight_kg = int(float(payload["net_weight_kg"]))
                except (ValueError, TypeError):
                    pass
            
            payload_kg = None
            if payload.get("payload_kg"):
                try:
                    payload_kg = int(float(payload["payload_kg"]))
                except (ValueError, TypeError):
                    pass
            
            engine_cm3 = None
            if payload.get("engine_cm3"):
                try:
                    engine_cm3 = int(float(payload["engine_cm3"]))
                except (ValueError, TypeError):
                    pass
            
            seats = None
            if payload.get("seats"):
                try:
                    seats = int(float(payload["seats"]))
                except (ValueError, TypeError):
                    pass
            
            power_kw = None
            if payload.get("power_kw"):
                try:
                    power_kw = float(payload["power_kw"])
                except (ValueError, TypeError):
                    pass
            
            year_model = None
            if payload.get("year_model"):
                try:
                    year_model = int(float(payload["year_model"]))
                except (ValueError, TypeError):
                    pass
            
            year_calendar = None
            if payload.get("year_calendar"):
                try:
                    year_calendar = int(float(payload["year_calendar"]))
                except (ValueError, TypeError):
                    pass
            
            quantity = None
            if payload.get("quantity"):
                try:
                    quantity = float(payload["quantity"])
                except (ValueError, TypeError):
                    pass
            
            # Оновлюємо запис
            cursor.execute("""
                UPDATE vehicles SET
                    vehicle_type = ?,
                    brand = ?,
                    uktzed = ?,
                    description = ?,
                    producer_country = ?,
                    gross_weight = ?,
                    net_weight = ?,
                    gross_weight_kg = ?,
                    net_weight_kg = ?,
                    payload_kg = ?,
                    engine_cm3 = ?,
                    seats = ?,
                    power_kw = ?,
                    wheel_formula = ?,
                    year_model = ?,
                    year_calendar = ?,
                    quantity = ?,
                    serial_number = ?,
                    unit_human = ?
                WHERE id = ?
            """, (
                vehicle_type,
                brand,
                uktzed,
                description,
                producer_country,
                gross_weight,
                net_weight,
                gross_weight_kg,
                net_weight_kg,
                payload_kg,
                engine_cm3,
                seats,
                power_kw,
                wheel_formula,
                year_model,
                year_calendar,
                quantity,
                serial_number,
                unit_human,
                row_id,
            ))
            
            updated += 1
            
        except Exception as e:
            errors += 1
            print(f"  ❌ Помилка в записі {row_id}: {e}")
    
    conn.commit()
    
    print(f"  ✅ Оновлено записів: {updated}")
    if errors:
        print(f"  ❌ Помилок: {errors}")
    
    return updated, errors


def create_indexes(conn, cursor):
    """Створює індекси на нові колонки"""
    
    indexes = [
        ("idx_vehicles_vehicle_type", "vehicles(vehicle_type)"),
        ("idx_vehicles_brand", "vehicles(brand)"),
        ("idx_vehicles_year_model", "vehicles(year_model)"),
        ("idx_vehicles_uktzed", "vehicles(uktzed)"),
    ]
    
    created = []
    
    for idx_name, idx_def in indexes:
        try:
            cursor.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {idx_def}")
            created.append(idx_name)
        except sqlite3.OperationalError as e:
            print(f"  ⚠️ Помилка створення індексу {idx_name}: {e}")
    
    conn.commit()
    
    if created:
        print(f"  ✅ Створено індексів: {len(created)}")
        for idx in created:
            print(f"     - {idx}")
    
    return created


def verify_migration(cursor):
    """Перевіряє результати міграції"""
    
    # Перевіряємо кількість записів з vehicle_type
    cursor.execute("SELECT COUNT(*) FROM vehicles WHERE vehicle_type IS NOT NULL")
    with_vehicle_type = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM vehicles")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM vehicles WHERE brand IS NOT NULL")
    with_brand = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM vehicles WHERE uktzed IS NOT NULL")
    with_uktzed = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM vehicles WHERE year_model IS NOT NULL")
    with_year = cursor.fetchone()[0]
    
    print(f"\n  📊 Результати верифікації:")
    print(f"     - Всього записів: {total}")
    print(f"     - З vehicle_type: {with_vehicle_type} ({with_vehicle_type*100//total if total else 0}%)")
    print(f"     - З brand: {with_brand} ({with_brand*100//total if total else 0}%)")
    print(f"     - З uktzed: {with_uktzed} ({with_uktzed*100//total if total else 0}%)")
    print(f"     - З year_model: {with_year} ({with_year*100//total if total else 0}%)")
    
    # Перевіряємо кілька конкретних записів
    cursor.execute("""
        SELECT id, vehicle_type, brand, model, vin, year_model
        FROM vehicles
        WHERE vehicle_type IS NOT NULL
        LIMIT 5
    """)
    samples = cursor.fetchall()
    
    if samples:
        print(f"\n  📋 Приклади мігрованих записів:")
        for sample in samples:
            print(f"     ID:{sample[0]} | {sample[1]} | {sample[2]} {sample[3]} | VIN:{sample[4]} | {sample[5]}")
    
    return with_vehicle_type, total


def main():
    print("=" * 60)
    print("🔄 МІГРАЦІЯ БД: Нормалізація таблиці vehicles")
    print("=" * 60)
    
    if not DB_PATH.exists():
        print(f"❌ БД не знайдено: {DB_PATH}")
        return 1
    
    print(f"\n📁 БД: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Етап 1: Додаємо колонки
        print("\n📌 Етап 1: Додавання колонок...")
        add_columns(conn, cursor)
        
        # Етап 2: Заповнюємо колонки
        print("\n📌 Етап 2: Заповнення колонок з payload_json...")
        populate_columns(conn, cursor)
        
        # Етап 3: Створюємо індекси
        print("\n📌 Етап 3: Створення індексів...")
        create_indexes(conn, cursor)
        
        # Етап 4: Верифікація
        print("\n📌 Етап 4: Верифікація...")
        verify_migration(cursor)
        
        print("\n" + "=" * 60)
        print("✅ МІГРАЦІЯ ЗАВЕРШЕНА УСПІШНО")
        print("=" * 60)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ КРИТИЧНА ПОМИЛКА: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

