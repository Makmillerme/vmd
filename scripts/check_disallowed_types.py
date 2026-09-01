#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Перевірка заборонених типів з картками"""

import sys
import asyncio
import codecs
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

async def main():
    from vmd_extractor.core.database import VMDDatabase
    from vmd_extractor.config import DB_PATH, DISALLOWED_TRELLO_TYPES
    
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        placeholders = ','.join(['?' for _ in DISALLOWED_TRELLO_TYPES])
        cursor = await conn.execute(f"""
            SELECT v.vehicle_type, COUNT(*) as count
            FROM vehicles v
            JOIN trello_cards tc ON v.id = tc.vehicle_id
            WHERE v.vehicle_type IN ({placeholders})
            GROUP BY v.vehicle_type
        """, list(DISALLOWED_TRELLO_TYPES))
        rows = await cursor.fetchall()
    
    if rows:
        print("Заборонені типи з картками:")
        for row in rows:
            print(f"  {row['vehicle_type']}: {row['count']} карток")
        print(f"\nВсього: {sum(r['count'] for r in rows)} карток")
        print("\nРекомендація: запустіть cleanup через Trello меню")
    else:
        print("Заборонені типи не мають карток - все добре!")

if __name__ == "__main__":
    asyncio.run(main())

