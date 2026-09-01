#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест парсингу для різних типів техніки
Перевірка логіки VIN/serial_number для кожного типу
"""

import sys
import asyncio
import codecs
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def print_header(text):
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80)

def print_test(name, status, details=""):
    symbol = "✅" if status else "❌"
    print(f"  {symbol} {name}")
    if details:
        print(f"     {details}")

async def test_parsing_logic():
    """Тест логіки парсингу для різних типів техніки"""
    print_header("ТЕСТ ПАРСИНГУ ПО ТИПАХ ТЕХНІКИ")
    
    from vmd_extractor.core.database import VMDDatabase
    from vmd_extractor.config import DB_PATH
    
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    import aiosqlite
    
    # Тест 1: Контейнери
    print_header("1. КОНТЕЙНЕРИ (змінні кузови)")
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT id, vin, serial_number, vehicle_type, brand, model
            FROM vehicles
            WHERE vehicle_type LIKE '%контейнер%' OR vehicle_type LIKE '%змінний кузов%'
            LIMIT 10
        """)
        containers = await cursor.fetchall()
    
    if containers:
        print(f"  Знайдено {len(containers)} контейнерів:")
        for row in containers:
            vtype = row["vehicle_type"] or "N/A"
            vin = row["vin"] or "N/A"
            sn = row["serial_number"] or "N/A"
            brand = row["brand"] or "N/A"
            model = row["model"] or "N/A"
            
            # Перевірка логіки
            has_vin = vin and vin != "N/A"
            has_sn = sn and sn != "N/A"
            
            if has_vin:
                print_test(f"Контейнер {row['id']}: VIN={vin}", True, f"Brand={brand}, Model={model}")
            elif has_sn:
                print_test(f"Контейнер {row['id']}: SN={sn} (має бути в VIN)", 
                          vin == sn, f"VIN={vin}, SN={sn}")
            else:
                print_test(f"Контейнер {row['id']}: без VIN/SN", False, "Потрібно мати хоча б один")
    else:
        print("  ⚠️  Контейнери не знайдено в БД")
    
    # Тест 2: Спецтехніка
    print_header("2. СПЕЦТЕХНІКА")
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT id, vin, serial_number, vehicle_type, brand, model
            FROM vehicles
            WHERE vehicle_type LIKE '%спецтехніка%' OR vehicle_type LIKE '%спеціальн%'
            LIMIT 10
        """)
        special = await cursor.fetchall()
    
    if special:
        print(f"  Знайдено {len(special)} спецтехніки:")
        for row in special:
            vtype = row["vehicle_type"] or "N/A"
            vin = row["vin"] or "N/A"
            sn = row["serial_number"] or "N/A"
            brand = row["brand"] or "N/A"
            model = row["model"] or "N/A"
            
            has_vin = vin and vin != "N/A"
            has_sn = sn and sn != "N/A"
            
            if has_vin:
                print_test(f"Спецтехніка {row['id']}: VIN={vin}", True, f"Brand={brand}, Model={model}")
            elif has_sn:
                print_test(f"Спецтехніка {row['id']}: SN={sn} (має бути в VIN)", 
                          vin == sn, f"VIN={vin}, SN={sn}")
            else:
                print_test(f"Спецтехніка {row['id']}: без VIN/SN", False, "Потрібно мати хоча б один")
    else:
        print("  ⚠️  Спецтехніка не знайдено в БД")
    
    # Тест 3: Вантажні автомобілі
    print_header("3. ВАНТАЖНІ АВТОМОБІЛІ")
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT id, vin, serial_number, vehicle_type, brand, model
            FROM vehicles
            WHERE vehicle_type LIKE '%вантажний%' AND vehicle_type NOT LIKE '%легковий%'
            LIMIT 10
        """)
        cargo = await cursor.fetchall()
    
    if cargo:
        print(f"  Знайдено {len(cargo)} вантажних автомобілів:")
        without_vin = 0
        for row in cargo:
            vtype = row["vehicle_type"] or "N/A"
            vin = row["vin"] or "N/A"
            sn = row["serial_number"] or "N/A"
            brand = row["brand"] or "N/A"
            model = row["model"] or "N/A"
            
            has_vin = vin and vin != "N/A"
            
            if has_vin:
                print_test(f"Вантажний {row['id']}: VIN={vin}", True, f"Brand={brand}, Model={model}")
            else:
                without_vin += 1
                print_test(f"Вантажний {row['id']}: без VIN", False, f"Brand={brand}, Model={model} - VIN обов'язковий!")
        
        if without_vin > 0:
            print(f"\n  ⚠️  Знайдено {without_vin} вантажних автомобілів без VIN (мають бути обов'язково)")
    else:
        print("  ⚠️  Вантажні автомобілі не знайдено в БД")
    
    # Тест 4: Статистика по типах
    print_header("4. СТАТИСТИКА ПО ТИПАХ")
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT 
                vehicle_type,
                COUNT(*) as total,
                COUNT(vin) as with_vin,
                COUNT(serial_number) as with_sn,
                COUNT(CASE WHEN vin IS NOT NULL AND vin != '' AND serial_number IS NOT NULL AND serial_number != '' THEN 1 END) as with_both
            FROM vehicles
            WHERE vehicle_type IS NOT NULL AND vehicle_type != ''
            GROUP BY vehicle_type
            ORDER BY total DESC
        """)
        stats = await cursor.fetchall()
    
    print(f"  Всього типів: {len(stats)}\n")
    for row in stats:
        vtype = row["vehicle_type"]
        total = row["total"]
        with_vin = row["with_vin"]
        with_sn = row["with_sn"]
        with_both = row["with_both"]
        
        print(f"  {vtype}:")
        print(f"     Всього: {total}, з VIN: {with_vin}, з SN: {with_sn}, з обома: {with_both}")
    
    # Тест 5: Перевірка логіки в парсері
    print_header("5. ПЕРЕВІРКА ЛОГІКИ В ПАРСЕРІ")
    
    # Симулюємо різні сценарії
    test_cases = [
        {
            "name": "Контейнер з VIN",
            "vehicle_type": "Контейнер (змінний кузов)",
            "vin": "VIN123",
            "serial_number": "SN456",
            "expected_vin": "VIN123",  # VIN має перевагу
            "expected_sn": "SN456"
        },
        {
            "name": "Контейнер без VIN, з SN",
            "vehicle_type": "Контейнер (змінний кузов)",
            "vin": "",
            "serial_number": "SN789",
            "expected_vin": "SN789",  # SN копіюється в VIN
            "expected_sn": "SN789"
        },
        {
            "name": "Спецтехніка з VIN",
            "vehicle_type": "Спецтехніка",
            "vin": "VIN999",
            "serial_number": "SN111",
            "expected_vin": "VIN999",  # VIN має перевагу
            "expected_sn": "SN111"
        },
        {
            "name": "Спецтехніка без VIN, з SN",
            "vehicle_type": "Спецтехніка",
            "vin": "",
            "serial_number": "SN222",
            "expected_vin": "SN222",  # SN копіюється в VIN
            "expected_sn": "SN222"
        },
        {
            "name": "Вантажний автомобіль з VIN",
            "vehicle_type": "Автомобіль вантажний",
            "vin": "VIN333",
            "serial_number": "SN444",
            "expected_vin": "VIN333",  # VIN завжди присутній
            "expected_sn": "SN444"
        }
    ]
    
    print("  Симуляція логіки парсера:\n")
    for case in test_cases:
        vehicle_type = case["vehicle_type"]
        vehicle_type_lower = vehicle_type.lower()
        is_container = "контейнер" in vehicle_type_lower or "змінний кузов" in vehicle_type_lower
        is_special_equipment = "спеціальн" in vehicle_type_lower or "спецтехніка" in vehicle_type_lower
        
        vin = case["vin"]
        serial_number = case["serial_number"]
        
        # Логіка з парсера
        if is_container or is_special_equipment:
            if not vin and serial_number:
                vin = serial_number
        
        expected_vin = case["expected_vin"]
        expected_sn = case["expected_sn"]
        
        vin_ok = vin == expected_vin
        sn_ok = serial_number == expected_sn
        
        if vin_ok and sn_ok:
            print_test(case["name"], True, f"VIN={vin}, SN={serial_number}")
        else:
            print_test(case["name"], False, 
                      f"Очікувано: VIN={expected_vin}, SN={expected_sn}, Отримано: VIN={vin}, SN={serial_number}")

if __name__ == "__main__":
    asyncio.run(test_parsing_logic())

