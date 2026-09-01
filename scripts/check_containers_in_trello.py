#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для перевірки наявності карток "Змінних кузовів" (Контейнер (змінний кузов)) в Trello
за останні 2 місяці та аналізу проблеми, якщо їх немає.
"""

import asyncio
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Виправляємо кодування для Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Додаємо корінь проекту до шляху
project_root = Path(__file__).parent.parent  # scripts -> корінь проекту
sys.path.insert(0, str(project_root))

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.config import DB_PATH, get_trello_label_for_vehicle_type_async
import aiosqlite
import json


async def check_containers_in_trello():
    """Перевіряє наявність карток 'Змінних кузовів' в Trello за останні 2 місяці"""
    
    print("=" * 80)
    print("ПЕРЕВІРКА КАРТОК 'ЗМІННИХ КУЗОВІВ' В TRELLO")
    print("=" * 80)
    
    # Обчислюємо дату 2 місяці тому
    today = datetime.now().date()
    two_months_ago = today - timedelta(days=60)
    
    print(f"\nПеріод перевірки: з {two_months_ago} по {today}")
    print(f"Шукаємо vehicles з типом 'Контейнер (змінний кузов)'\n")
    
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    # Знаходимо всі vehicles з типом "Контейнер (змінний кузов)" за останні 2 місяці
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        # Використовуємо нормалізовану колонку vehicle_type
        cursor = await conn.execute("""
            SELECT 
                v.id,
                v.mrn,
                v.vin,
                v.model,
                v.brand,
                v.vehicle_type,
                v.create_at_ccd,
                v.created_at,
                v.pdf_url,
                pf.filename as source_file
            FROM vehicles v
            LEFT JOIN processed_files pf ON pf.id = v.processed_file_id
            WHERE (
                  v.vehicle_type = 'Контейнер (змінний кузов)'
                  OR v.vehicle_type LIKE '%контейнер%змінний%кузов%'
                  OR v.vehicle_type LIKE '%Контейнер%змінний%кузов%'
              )
              AND (
                  (v.create_at_ccd IS NOT NULL AND DATE(v.create_at_ccd) >= DATE(?))
                  OR (v.create_at_ccd IS NULL AND DATE(v.created_at) >= DATE(?))
              )
            ORDER BY v.create_at_ccd DESC, v.created_at DESC
        """, (two_months_ago.isoformat(), two_months_ago.isoformat()))
        
        rows = await cursor.fetchall()
    
    if not rows:
        print("[!] Не знайдено vehicles з типом 'Контейнер (змінний кузов)' за останні 2 місяці")
        return
    
    print(f"[OK] Знайдено {len(rows)} vehicles з типом 'Контейнер (змінний кузов)'\n")
    
    # Перевіряємо кожен vehicle
    vehicles_with_cards = []
    vehicles_without_cards = []
    vehicles_without_label = []
    vehicles_missing_fields = []
    vehicles_disallowed = []
    
    # Перевіряємо чи є мітка для цього типу
    label_id = await get_trello_label_for_vehicle_type_async("Контейнер (змінний кузов)", db)
    
    print(f"Мітка Trello для 'Контейнер (змінний кузов)': {'[OK] Є' if label_id else '[!] Немає'}")
    if label_id:
        print(f"    ID мітки: {label_id}\n")
    else:
        print(f"    [!!!] ПРОБЛЕМА: Немає мітки в БД для цього типу!\n")
    
    for row in rows:
        vehicle_id = row["id"]
        
        # Використовуємо нормалізовані колонки
        brand = (row["brand"] or "").strip()
        model = (row["model"] or "").strip()
        vin = (row["vin"] or "").strip()
        vehicle_type = (row["vehicle_type"] or "").strip()
        
        # Перевіряємо чи є Trello картка
        trello_card = await db.get_trello_card_by_vehicle_id(vehicle_id)
        
        vehicle_info = {
            "id": vehicle_id,
            "brand": brand,
            "model": model,
            "vin": vin,
            "vehicle_type": vehicle_type,
            "mrn": row["mrn"],
            "create_at_ccd": row["create_at_ccd"],
            "source_file": row["source_file"],
            "trello_card_id": trello_card.get("trello_card_id") if trello_card else None,
            "has_card": bool(trello_card and trello_card.get("trello_card_id"))
        }
        
        # Аналізуємо проблеми
        if not brand or not model or not vin:
            vehicles_missing_fields.append(vehicle_info)
        elif vehicle_type in ["Автомобіль легковий"]:
            vehicles_disallowed.append(vehicle_info)
        elif not label_id:
            vehicles_without_label.append(vehicle_info)
        elif vehicle_info["has_card"]:
            vehicles_with_cards.append(vehicle_info)
        else:
            vehicles_without_cards.append(vehicle_info)
    
    # Виводимо результати
    print("=" * 80)
    print("РЕЗУЛЬТАТИ АНАЛІЗУ")
    print("=" * 80)
    
    print(f"\n[OK] Vehicles З картками Trello: {len(vehicles_with_cards)}")
    print(f"[!] Vehicles БЕЗ карток Trello: {len(vehicles_without_cards)}")
    print(f"[!] Vehicles без мітки в БД: {len(vehicles_without_label)}")
    print(f"[!] Vehicles з відсутніми полями (brand/model/vin): {len(vehicles_missing_fields)}")
    print(f"[X] Vehicles забороненого типу: {len(vehicles_disallowed)}")
    
    # Детальна інформація про vehicles без карток
    if vehicles_without_cards:
        print(f"\n{'=' * 80}")
        print(f"ДЕТАЛЬНА ІНФОРМАЦІЯ ПРО VEHICLES БЕЗ КАРТОК ({len(vehicles_without_cards)}):")
        print("=" * 80)
        
        for idx, vehicle in enumerate(vehicles_without_cards[:20], 1):  # Показуємо перші 20
            print(f"\n{idx}. Vehicle ID: {vehicle['id']}")
            print(f"   Brand: {vehicle['brand'] or 'N/A'}")
            print(f"   Model: {vehicle['model'] or 'N/A'}")
            print(f"   VIN: {vehicle['vin'] or 'N/A'}")
            print(f"   MRN: {vehicle['mrn'] or 'N/A'}")
            print(f"   Тип: {vehicle['vehicle_type']}")
            print(f"   Дата ВМД: {vehicle['create_at_ccd'] or 'N/A'}")
            print(f"   Файл: {vehicle['source_file'] or 'N/A'}")
            print(f"   Trello картка: [X] Відсутня")
            
            # Перевіряємо причину
            if not vehicle['brand'] or not vehicle['model'] or not vehicle['vin']:
                print(f"   [!!!] ПРИЧИНА: Відсутні обов'язкові поля (brand/model/vin)")
            elif not label_id:
                print(f"   [!!!] ПРИЧИНА: Немає мітки Trello в БД для типу '{vehicle['vehicle_type']}'")
            else:
                print(f"   [!!!] ПРИЧИНА: Картка не була створена (можливо, не синхронізовано)")
        
        if len(vehicles_without_cards) > 20:
            print(f"\n   ... та ще {len(vehicles_without_cards) - 20} vehicles")
    
    # Детальна інформація про vehicles без мітки
    if vehicles_without_label:
        print(f"\n{'=' * 80}")
        print(f"VEHICLES БЕЗ МІТКИ В БД ({len(vehicles_without_label)}):")
        print("=" * 80)
        print("[!!!] Ці vehicles не можуть бути створені в Trello, бо немає мітки!")
        print("[i] Рішення: Створіть мітку через меню 'Управління Trello' -> 'Управління мітками Trello' -> 'Створити мітки для типів авто'")
        
        # Показуємо приклади
        for idx, vehicle in enumerate(vehicles_without_label[:10], 1):
            print(f"\n{idx}. {vehicle['brand']} {vehicle['model']} {vehicle['vin']}")
            print(f"   Тип: {vehicle['vehicle_type']}")
            print(f"   Дата ВМД: {vehicle['create_at_ccd'] or 'N/A'}")
    
    # Детальна інформація про vehicles з відсутніми полями
    if vehicles_missing_fields:
        print(f"\n{'=' * 80}")
        print(f"VEHICLES З ВІДСУТНІМИ ПОЛЯМИ ({len(vehicles_missing_fields)}):")
        print("=" * 80)
        print("[!!!] Ці vehicles НЕ МОЖУТЬ бути створені в Trello, бо відсутні обов'язкові поля!")
        print("[i] Обов'язкові поля для створення картки: brand, model, vin")
        print()
        
        for idx, vehicle in enumerate(vehicles_missing_fields[:20], 1):
            print(f"\n{idx}. Vehicle ID: {vehicle['id']}")
            print(f"   Brand: {'[OK]' if vehicle['brand'] else '[X]'} {vehicle['brand'] or 'Відсутнє'}")
            print(f"   Model: {'[OK]' if vehicle['model'] else '[X]'} {vehicle['model'] or 'Відсутнє'}")
            print(f"   VIN: {'[OK]' if vehicle['vin'] else '[X]'} {vehicle['vin'] or 'Відсутнє'}")
            print(f"   MRN: {vehicle['mrn'] or 'N/A'}")
            print(f"   Дата ВМД: {vehicle['create_at_ccd'] or 'N/A'}")
            print(f"   Файл: {vehicle['source_file'] or 'N/A'}")
            
            # Перевіряємо чи є Trello картка (можливо, була створена раніше)
            if vehicle.get('trello_card_id'):
                print(f"   Trello картка: [OK] Є (ID: {vehicle['trello_card_id']})")
            else:
                print(f"   Trello картка: [X] Відсутня")
        
        if len(vehicles_missing_fields) > 20:
            print(f"\n   ... та ще {len(vehicles_missing_fields) - 20} vehicles")
    
    # Підсумок
    print(f"\n{'=' * 80}")
    print("ПІДСУМОК")
    print("=" * 80)
    
    total_problems = len(vehicles_without_cards) + len(vehicles_without_label) + len(vehicles_missing_fields)
    
    if total_problems == 0:
        print("[OK] Всі vehicles з типом 'Контейнер (змінний кузов)' мають картки в Trello!")
    else:
        print(f"[!] Знайдено {total_problems} vehicles з проблемами:")
        
        if vehicles_without_label:
            print(f"   - {len(vehicles_without_label)} vehicles без мітки в БД (не можуть бути створені)")
            print("     [i] Рішення: Створіть мітку для 'Контейнер (змінний кузов)' через меню управління мітками")
        
        if vehicles_without_cards:
            print(f"   - {len(vehicles_without_cards)} vehicles без карток (можливо, не синхронізовано)")
            print("     [i] Рішення: Запустіть синхронізацію з Trello")
        
        if vehicles_missing_fields:
            print(f"   - {len(vehicles_missing_fields)} vehicles з відсутніми полями (brand/model/vin)")
            print("     [i] Це може бути проблема парсингу XML")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(check_containers_in_trello())
    except KeyboardInterrupt:
        print("\n\nОперацію перервано користувачем")
    except Exception as e:
        print(f"\n\n[ERROR] Помилка: {e}")
        import traceback
        traceback.print_exc()

