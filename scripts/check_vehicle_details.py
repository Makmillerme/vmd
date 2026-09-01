#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для детальної перевірки автомобіля
"""

import asyncio
import aiosqlite
import sys
import json
from pathlib import Path

# Додаємо корінь проекту до шляху
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.config import DB_PATH
from vmd_extractor.utils.data_extractor import extract_vehicle_type_from_description

async def check_vehicle_details(vin: str):
    """Детальна перевірка автомобіля"""
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    vin_upper = vin.strip().upper()
    
    print(f"\n{'='*80}")
    print(f"ДЕТАЛЬНА ПЕРЕВІРКА АВТОМОБІЛЯ")
    print(f"{'='*80}")
    print(f"VIN: {vin_upper}\n")
    
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        
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
                v.payload_json,
                pf.filename as source_file
            FROM vehicles v
            LEFT JOIN processed_files pf ON pf.id = v.processed_file_id
            WHERE UPPER(v.vin) = ?
            LIMIT 1
        """
        
        cursor = await conn.execute(query, (vin_upper,))
        row = await cursor.fetchone()
        
        if not row:
            print(f"[ERROR] Автомобіль з VIN '{vin_upper}' не знайдено в базі даних")
            return
        
        print(f"{'='*80}")
        print("ДАНІ З БАЗИ ДАНИХ:")
        print(f"{'='*80}")
        print(f"ID: {row['id']}")
        print(f"MRN: {row['mrn']}")
        print(f"VIN: {row['vin']}")
        print(f"Марка: {row['brand']}")
        print(f"Модель: {row['model']}")
        print(f"Тип техніки (з БД): {row['vehicle_type']}")
        print(f"Файл джерела: {row['source_file']}")
        print(f"Дата створення ВМД: {row['create_at_ccd']}")
        print(f"Дата створення запису: {row['created_at']}")
        
        description = row['description']
        print(f"\n{'='*80}")
        print("ОПИС (description):")
        print(f"{'='*80}")
        if description:
            print(description)
        else:
            print("[ПУСТО]")
        
        # Перевіряємо payload_json
        payload_json = row['payload_json']
        if payload_json:
            try:
                payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
                print(f"\n{'='*80}")
                print("PAYLOAD JSON:")
                print(f"{'='*80}")
                print(json.dumps(payload, indent=2, ensure_ascii=False))
            except:
                print("\n[ERROR] Не вдалося розпарсити payload_json")
        
        # Тестуємо визначення типу з опису
        print(f"\n{'='*80}")
        print("ТЕСТУВАННЯ ВИЗНАЧЕННЯ ТИПУ:")
        print(f"{'='*80}")
        if description:
            extracted_type = extract_vehicle_type_from_description(description)
            print(f"Визначений тип з опису: '{extracted_type}'")
            print(f"Тип в БД: '{row['vehicle_type']}'")
            if extracted_type != row['vehicle_type']:
                print(f"\n[WARNING] Різниця між визначеним типом та типом в БД!")
                print(f"  Визначено: '{extracted_type}'")
                print(f"  В БД: '{row['vehicle_type']}'")
            else:
                print("\n[OK] Типи співпадають")
        else:
            print("[WARNING] Немає опису для тестування")
        
        # Аналіз опису
        if description:
            print(f"\n{'='*80}")
            print("АНАЛІЗ ОПИСУ:")
            print(f"{'='*80}")
            desc_lower = description.lower()
            
            keywords = {
                "легковий": "легковий" in desc_lower,
                "вантажний": "вантажний" in desc_lower,
                "автомобіль": "автомобіль" in desc_lower,
                "фургон": "фургон" in desc_lower,
                "контейнер": "контейнер" in desc_lower,
                "сідельний": "сідельний" in desc_lower,
                "тягач": "тягач" in desc_lower,
                "напівпричіп": "напівпричіп" in desc_lower,
                "причіп": "причіп" in desc_lower,
            }
            
            print("Знайдені ключові слова:")
            for keyword, found in keywords.items():
                status = "[+]" if found else "[-]"
                print(f"  {status} {keyword}")
            
            # Шукаємо фрази про тип кузова
            print("\nФрази про тип кузова:")
            body_type_patterns = [
                r'тип\s+кузова[:\-]?\s*([^,\n\.]+)',
                r'кузов[:\-]?\s*([^,\n\.]+)',
            ]
            import re
            for pattern in body_type_patterns:
                matches = re.findall(pattern, description, re.IGNORECASE)
                if matches:
                    for match in matches:
                        print(f"  Знайдено: '{match.strip()}'")
        
        print(f"\n{'='*80}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Використання: python check_vehicle_details.py <VIN>")
        sys.exit(1)
    
    vin = sys.argv[1]
    asyncio.run(check_vehicle_details(vin))
