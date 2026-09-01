#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для перевірки чому машина не потрапила в Trello
"""

import asyncio
import aiosqlite
import json
import sys
from pathlib import Path

# Додаємо корінь проекту до шляху
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.config import DB_PATH, get_trello_label_for_vehicle_type_async, DISALLOWED_TRELLO_TYPES

async def check_vehicle(identifier: str):
    """Перевіряє машину за ідентифікатором (MRN, filename, або VIN)"""
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        
        # Шукаємо за MRN, filename або VIN
        query = """
            SELECT 
                v.id,
                v.mrn,
                v.vin,
                v.brand,
                v.model,
                v.vehicle_type,
                v.create_at_ccd,
                v.created_at,
                v.pdf_url,
                v.processed_file_id,
                pf.filename as source_file,
                tc.trello_card_id,
                tc.is_present,
                tc.last_sync_status
            FROM vehicles v
            LEFT JOIN processed_files pf ON pf.id = v.processed_file_id
            LEFT JOIN trello_cards tc ON tc.vehicle_id = v.id
            WHERE v.mrn LIKE ? 
               OR pf.filename LIKE ?
               OR v.vin LIKE ?
            ORDER BY v.id DESC
            LIMIT 10
        """
        
        pattern = f"%{identifier}%"
        cursor = await conn.execute(query, (pattern, pattern, pattern))
        rows = await cursor.fetchall()
        
        if not rows:
            print(f"[ERROR] Машину з ідентифікатором '{identifier}' не знайдено в базі даних")
            return
        
        print(f"[OK] Знайдено {len(rows)} записів:\n")
        
        for row in rows:
            vehicle_id = row['id']
            mrn = row['mrn']
            vin = row['vin']
            brand = row['brand']
            model = row['model']
            vehicle_type = row['vehicle_type']
            source_file = row['source_file']
            trello_card_id = row['trello_card_id']
            is_present = row['is_present']
            status = row['last_sync_status']
            
            print(f"{'='*80}")
            print(f"ID: {vehicle_id}")
            print(f"MRN: {mrn}")
            print(f"VIN: {vin}")
            print(f"Марка: {brand}")
            print(f"Модель: {model}")
            print(f"Тип техніки: {vehicle_type}")
            print(f"Файл: {source_file}")
            print(f"Trello Card ID: {trello_card_id or 'НЕ СТВОРЕНО'}")
            print(f"Trello Status: {status or 'НЕ СИНХРОНІЗОВАНО'}")
            print(f"Is Present: {is_present}")
            
            # Додаткова інформація про дати
            create_at_ccd = row['create_at_ccd'] if 'create_at_ccd' in row.keys() else None
            created_at = row['created_at'] if 'created_at' in row.keys() else None
            if create_at_ccd:
                print(f"Дата створення ВМД: {create_at_ccd}")
            if created_at:
                print(f"Дата створення запису: {created_at}")
            print()
            
            # Перевіряємо чому не синхронізувалось
            issues = []
            
            # 1. Перевірка обов'язкових полів
            if not brand or not brand.strip():
                issues.append("[ERROR] Відсутня марка (brand)")
            if not model or not model.strip():
                issues.append("[ERROR] Відсутня модель (model)")
            if not vin or not vin.strip():
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
                else:
                    print(f"   [OK] Trello мітка знайдена: {label_id}")
            
            # 3. Перевірка чи є запис в trello_cards
            if not trello_card_id:
                issues.append("[ERROR] Картка Trello не створена (trello_card_id відсутній)")
            
            # 4. Перевірка статусу
            if status and status != 'success':
                issues.append(f"[WARNING] Статус синхронізації: {status}")
            
            if issues:
                print("ПРОБЛЕМИ:")
                for issue in issues:
                    print(f"   {issue}")
            else:
                print("[OK] Всі перевірки пройдено успішно")
            
            print()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Використання: python check_vehicle_trello.py <identifier>")
        print("   identifier - MRN, filename або VIN")
        sys.exit(1)
    
    identifier = sys.argv[1]
    asyncio.run(check_vehicle(identifier))
