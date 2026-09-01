#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для синхронізації конкретної машини з Trello
"""

import asyncio
import sys
from pathlib import Path

# Додаємо корінь проекту до шляху
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.core.orchestrator import VMDOrchestrator
from vmd_extractor.config import DB_PATH

async def sync_vehicle(identifier: str):
    """Синхронізує машину з Trello за ідентифікатором (ID, MRN, filename або VIN)"""
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    # Шукаємо vehicle
    vehicle_id = None
    
    # Спробуємо як ID
    try:
        vehicle_id = int(identifier)
    except ValueError:
        pass
    
    if not vehicle_id:
        # Шукаємо за MRN, filename або VIN
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            pattern = f"%{identifier}%"
            cursor = await conn.execute("""
                SELECT v.id
                FROM vehicles v
                LEFT JOIN processed_files pf ON pf.id = v.processed_file_id
                WHERE v.mrn LIKE ? 
                   OR pf.filename LIKE ?
                   OR v.vin LIKE ?
                LIMIT 1
            """, (pattern, pattern, pattern))
            row = await cursor.fetchone()
            if row:
                vehicle_id = row['id']
    
    if not vehicle_id:
        print(f"[ERROR] Машину з ідентифікатором '{identifier}' не знайдено")
        return
    
    print(f"[OK] Знайдено vehicle ID: {vehicle_id}")
    print(f"[INFO] Запуск синхронізації з Trello...")
    
    # Створюємо оркестратор та синхронізуємо
    orchestrator = VMDOrchestrator(database=db)
    await orchestrator._sync_vehicles_to_trello(vehicle_ids=[vehicle_id])
    
    # Перевіряємо результат
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT tc.trello_card_id, tc.last_sync_status
            FROM trello_cards tc
            WHERE tc.vehicle_id = ?
        """, (vehicle_id,))
        row = await cursor.fetchone()
        if row and row['trello_card_id']:
            print(f"[OK] Картка Trello створена: {row['trello_card_id']}")
            print(f"[INFO] Статус: {row['last_sync_status']}")
        else:
            print(f"[ERROR] Картка Trello не створена")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Використання: python sync_vehicle_to_trello.py <identifier>")
        print("   identifier - ID, MRN, filename або VIN")
        sys.exit(1)
    
    identifier = sys.argv[1]
    asyncio.run(sync_vehicle(identifier))
