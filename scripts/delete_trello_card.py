#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для видалення Trello картки (залишає запис в БД)
"""

import asyncio
import sys
import aiosqlite
from pathlib import Path

# Додаємо корінь проекту до шляху
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.config import DB_PATH, TRELLO_ENABLED, TRELLO_API_KEY, TRELLO_API_TOKEN

async def delete_trello_card(identifier: str):
    """Видаляє Trello картку за ідентифікатором (ID, MRN, filename або VIN)"""
    if not TRELLO_ENABLED or not TRELLO_API_KEY or not TRELLO_API_TOKEN:
        print("[ERROR] Trello не налаштовано")
        return
    
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    # Шукаємо vehicle та trello_card_id
    vehicle_id = None
    trello_card_id = None
    
    # Спробуємо як ID
    try:
        vehicle_id = int(identifier)
    except ValueError:
        pass
    
    if not vehicle_id:
        # Шукаємо за MRN, filename або VIN
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
    
    # Отримуємо trello_card_id
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("""
            SELECT tc.trello_card_id
            FROM trello_cards tc
            WHERE tc.vehicle_id = ?
        """, (vehicle_id,))
        row = await cursor.fetchone()
        if row and row['trello_card_id']:
            trello_card_id = row['trello_card_id']
    
    if not trello_card_id:
        print(f"[INFO] Trello картка не знайдена для vehicle ID {vehicle_id}")
        return
    
    print(f"[INFO] Знайдено vehicle ID: {vehicle_id}")
    print(f"[INFO] Trello Card ID: {trello_card_id}")
    print(f"[INFO] Видалення картки з Trello...")
    
    # Видаляємо картку з Trello
    try:
        from vmd_extractor.utils.trello_integration import TrelloIntegration
        
        trello = TrelloIntegration(
            api_key=TRELLO_API_KEY,
            api_token=TRELLO_API_TOKEN,
            board_id="",  # Не потрібно для видалення
            list_id="",  # Не потрібно для видалення
            enabled=True,
        )
        
        success = await trello.delete_card(trello_card_id)
        
        if success:
            print(f"[OK] Картка видалена з Trello")
            
            # Оновлюємо запис в БД - видаляємо trello_card_id та встановлюємо is_present = 0
            async with aiosqlite.connect(db.db_path) as conn:
                await conn.execute("""
                    UPDATE trello_cards 
                    SET trello_card_id = NULL,
                        is_present = 0,
                        last_sync_status = 'deleted'
                    WHERE vehicle_id = ?
                """, (vehicle_id,))
                await conn.commit()
            
            print(f"[OK] Запис в БД оновлено (trello_card_id видалено, is_present = 0)")
            print(f"[INFO] Запис про vehicle залишився в таблиці vehicles")
        else:
            print(f"[ERROR] Не вдалося видалити картку з Trello")
    except Exception as e:
        print(f"[ERROR] Помилка видалення: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Використання: python delete_trello_card.py <identifier>")
        print("   identifier - ID, MRN, filename або VIN")
        sys.exit(1)
    
    identifier = sys.argv[1]
    asyncio.run(delete_trello_card(identifier))
