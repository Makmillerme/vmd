#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для перевірки чому вантажні машини не потрапили в Trello
"""

import asyncio
import aiosqlite
import sys
import os
from pathlib import Path

# Встановлюємо UTF-8 кодування для виводу
if sys.platform == 'win32':
    os.system('chcp 65001 > nul')
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

# Додаємо корінь проекту до шляху
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.config import DB_PATH, get_trello_label_for_vehicle_type_async, DISALLOWED_TRELLO_TYPES

async def check_vehicles_by_vins(vins: list):
    """Перевіряє машини за списком VIN"""
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    print(f"\n{'='*80}")
    print(f"ПЕРЕВІРКА {len(vins)} ВАНТАЖНИХ МАШИН")
    print(f"{'='*80}\n")
    
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        
        for vin in vins:
            vin_upper = vin.strip().upper()
            print(f"\n{'-'*80}")
            print(f"VIN: {vin_upper}")
            print(f"{'-'*80}")
            
            # Шукаємо машину за VIN
            query = """
                SELECT 
                    v.id,
                    v.mrn,
                    v.vin,
                    v.brand,
                    v.model,
                    v.vehicle_type,
                    v.description,
                    v.create_at_ccd,
                    v.created_at,
                    v.pdf_url,
                    pf.filename as source_file,
                    tc.trello_card_id,
                    tc.is_present,
                    tc.last_sync_status
                FROM vehicles v
                LEFT JOIN processed_files pf ON pf.id = v.processed_file_id
                LEFT JOIN trello_cards tc ON tc.vehicle_id = v.id
                WHERE UPPER(v.vin) = ?
                LIMIT 1
            """
            
            cursor = await conn.execute(query, (vin_upper,))
            row = await cursor.fetchone()
            
            if not row:
                print(f"[ERROR] Машину з VIN '{vin_upper}' не знайдено в базі даних")
                continue
            
            vehicle_id = row['id']
            mrn = row['mrn']
            vin_db = row['vin']
            brand = row['brand']
            model = row['model']
            vehicle_type = row['vehicle_type']
            description = row['description']
            source_file = row['source_file']
            trello_card_id = row['trello_card_id']
            is_present = row['is_present']
            status = row['last_sync_status']
            
            print(f"[OK] Знайдено в БД:")
            print(f"   ID: {vehicle_id}")
            print(f"   MRN: {mrn}")
            print(f"   VIN: {vin_db}")
            print(f"   Марка: {brand}")
            print(f"   Модель: {model}")
            print(f"   Тип техніки: {vehicle_type}")
            print(f"   Файл: {source_file}")
            print(f"   Trello Card ID: {trello_card_id or 'НЕ СТВОРЕНО'}")
            print(f"   Trello Status: {status or 'НЕ СИНХРОНІЗОВАНО'}")
            print(f"   Is Present: {is_present}")
            
            if description:
                desc_preview = description[:200] + "..." if len(description) > 200 else description
                print(f"   Опис (фрагмент): {desc_preview}")
            
            # Аналіз проблем
            issues = []
            warnings = []
            
            # 1. Перевірка обов'язкових полів
            if not brand or not brand.strip():
                issues.append("[ERROR] Відсутня марка (brand)")
            if not model or not model.strip():
                issues.append("[ERROR] Відсутня модель (model)")
            if not vin_db or not vin_db.strip():
                issues.append("[ERROR] Відсутній VIN")
            
            # 2. Перевірка типу техніки
            if not vehicle_type or not vehicle_type.strip():
                issues.append("[ERROR] Відсутній тип техніки (vehicle_type)")
            elif vehicle_type in DISALLOWED_TRELLO_TYPES:
                issues.append(f"[ERROR] Тип техніки '{vehicle_type}' заборонений для Trello")
            else:
                # Перевіряємо чи є мітка для цього типу
                label_id = await get_trello_label_for_vehicle_type_async(vehicle_type, db)
                if not label_id:
                    issues.append(f"[ERROR] Не знайдено Trello мітку для типу '{vehicle_type}'")
                    # Перевіряємо чи це вантажний автомобіль
                    vehicle_type_lower = vehicle_type.lower() if vehicle_type else ""
                    cargo_indicators = [
                        "фургон", "контейнеровоз", "бортовий", "тентована платформа",
                        "фургон рефрижератор", "фургон пластиковий", "фургон бортовий",
                        "фургон бортовий тентований", "фургон бортовий самоскид",
                        "вантажний"
                    ]
                    if any(indicator in vehicle_type_lower for indicator in cargo_indicators):
                        # Перевіряємо чи є мітка для базового типу "Автомобіль вантажний"
                        base_label_id = await db.get_trello_label_id("Автомобіль вантажний")
                        if base_label_id:
                            warnings.append(f"[WARNING] Тип '{vehicle_type}' схожий на вантажний, але немає окремої мітки. Можна використати базову мітку 'Автомобіль вантажний' ({base_label_id})")
                        else:
                            issues.append(f"[ERROR] Немає навіть базової мітки 'Автомобіль вантажний' в БД")
                else:
                    print(f"   [OK] Trello мітка знайдена: {label_id}")
            
            # 3. Перевірка чи є запис в trello_cards
            if not trello_card_id:
                issues.append("[ERROR] Картка Trello не створена (trello_card_id відсутній)")
            
            # 4. Перевірка статусу
            if status and status != 'success':
                warnings.append(f"[WARNING] Статус синхронізації: {status}")
            
            # Виводимо проблеми
            if issues:
                print(f"\nПРОБЛЕМИ:")
                for issue in issues:
                    print(f"   {issue}")
            
            if warnings:
                print(f"\nПОПЕРЕДЖЕННЯ:")
                for warning in warnings:
                    print(f"   {warning}")
            
            if not issues and not warnings:
                print(f"\n[OK] Всі перевірки пройдено успішно - машина повинна бути в Trello")
            
            # Перевіряємо чи є мітка в БД для цього типу
            if vehicle_type:
                print(f"\nПеревірка міток Trello в БД:")
                cursor = await conn.execute(
                    "SELECT vehicle_type, trello_label_id FROM trello_labels WHERE vehicle_type LIKE ?",
                    (f"%{vehicle_type}%",)
                )
                label_rows = await cursor.fetchall()
                if label_rows:
                    for lbl_row in label_rows:
                        print(f"   [OK] Знайдено: '{lbl_row['vehicle_type']}' -> {lbl_row['trello_label_id']}")
                else:
                    print(f"   [ERROR] Мітка для типу '{vehicle_type}' не знайдена в БД")
                    # Перевіряємо базову мітку
                    cursor = await conn.execute(
                        "SELECT vehicle_type, trello_label_id FROM trello_labels WHERE vehicle_type = ?",
                        ("Автомобіль вантажний",)
                    )
                    base_row = await cursor.fetchone()
                    if base_row:
                        print(f"   [INFO] Базова мітка 'Автомобіль вантажний' існує: {base_row['trello_label_id']}")
                    else:
                        print(f"   [ERROR] Базова мітка 'Автомобіль вантажний' також відсутня")
    
    print(f"\n{'='*80}")
    print("ПЕРЕВІРКА ЗАВЕРШЕНА")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    # Три проблемні VIN
    problem_vins = [
        "WDB9702581L830290",
        "WMAN44ZZ7FY328192",
        "WMAN15ZZ3KY386051"
    ]
    
    asyncio.run(check_vehicles_by_vins(problem_vins))
