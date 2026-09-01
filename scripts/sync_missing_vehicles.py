#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для синхронізації пропущених машин з Trello
"""

import asyncio
import sys
from pathlib import Path

# Додаємо корінь проекту до шляху
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.utils.trello_integration import TrelloIntegration
from vmd_extractor.utils.trello_sync_service import TrelloSyncService
from vmd_extractor.config import (
    DB_PATH,
    TRELLO_ENABLED,
    TRELLO_API_KEY,
    TRELLO_API_TOKEN,
    TRELLO_BOARD_ID,
    TRELLO_LIST_ID,
)

async def sync_vehicles_by_ids(vehicle_ids: list):
    """Синхронізує машини за списком ID"""
    print(f"\n{'='*80}")
    print(f"СИНХРОНІЗАЦІЯ {len(vehicle_ids)} МАШИН З TRELLO")
    print(f"{'='*80}\n")
    
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    # Перевіряємо чи машини існують
    vehicles = await db.get_vehicles_by_ids(vehicle_ids)
    if not vehicles:
        print("[ERROR] Не знайдено машин з вказаними ID")
        return
    
    print(f"[OK] Знайдено {len(vehicles)} машин для синхронізації:\n")
    for vehicle in vehicles:
        print(f"  - ID {vehicle['id']}: {vehicle.get('brand', '')} {vehicle.get('model', '')} {vehicle.get('vin', '')}")
    
    confirm = input("\nПродовжити синхронізацію? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Синхронізацію скасовано.")
        return
    
    # Перевірка конфігурації Trello
    if not TRELLO_ENABLED:
        print("[ERROR] Trello інтеграція вимкнена")
        return
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN:
        print("[ERROR] Trello API credentials не налаштовані")
        return
    
    # Створюємо Trello інтеграцію та сервіс синхронізації
    trello = TrelloIntegration(
        api_key=TRELLO_API_KEY,
        api_token=TRELLO_API_TOKEN,
        board_id=TRELLO_BOARD_ID,
        list_id=TRELLO_LIST_ID,
        enabled=True,
    )
    
    sync_service = TrelloSyncService(trello, db)
    
    print("\nЗапуск синхронізації...")
    
    def progress_callback(idx, total, result):
        action_symbols = {
            'created': '[+]',
            'updated': '[~]',
            'skipped': '[-]',
            'error': '[!]'
        }
        symbol = action_symbols.get(result.action, '[?]')
        print(f"  {symbol} [{idx}/{total}] Vehicle ID {result.vehicle_id}: {result.action}", end='\r')
    
    report = await sync_service.sync_vehicles(vehicles, progress_callback=progress_callback)
    
    print(f"\n\n{'='*80}")
    print("РЕЗУЛЬТАТИ СИНХРОНІЗАЦІЇ")
    print(f"{'='*80}")
    print(report.get_detailed_report())
    print(f"{'='*80}\n")

async def sync_vehicles_by_vins(vins: list):
    """Синхронізує машини за списком VIN"""
    print(f"\n{'='*80}")
    print(f"СИНХРОНІЗАЦІЯ МАШИН ЗА VIN")
    print(f"{'='*80}\n")
    
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    # Знаходимо машини за VIN
    vehicles = await db.get_vehicles_by_vins(vins)
    if not vehicles:
        print("[ERROR] Не знайдено машин з вказаними VIN")
        return
    
    print(f"[OK] Знайдено {len(vehicles)} машин:\n")
    for vehicle in vehicles:
        print(f"  - {vehicle.get('brand', '')} {vehicle.get('model', '')} {vehicle.get('vin', '')} (ID: {vehicle['id']})")
    
    confirm = input("\nПродовжити синхронізацію? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Синхронізацію скасовано.")
        return
    
    # Перевірка конфігурації Trello
    if not TRELLO_ENABLED:
        print("[ERROR] Trello інтеграція вимкнена")
        return
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN:
        print("[ERROR] Trello API credentials не налаштовані")
        return
    
    # Створюємо Trello інтеграцію та сервіс синхронізації
    trello = TrelloIntegration(
        api_key=TRELLO_API_KEY,
        api_token=TRELLO_API_TOKEN,
        board_id=TRELLO_BOARD_ID,
        list_id=TRELLO_LIST_ID,
        enabled=True,
    )
    
    sync_service = TrelloSyncService(trello, db)
    
    print("\nЗапуск синхронізації...")
    
    def progress_callback(idx, total, result):
        action_symbols = {
            'created': '[+]',
            'updated': '[~]',
            'skipped': '[-]',
            'error': '[!]'
        }
        symbol = action_symbols.get(result.action, '[?]')
        print(f"  {symbol} [{idx}/{total}] Vehicle ID {result.vehicle_id}: {result.action}", end='\r')
    
    report = await sync_service.sync_vehicles(vehicles, progress_callback=progress_callback)
    
    print(f"\n\n{'='*80}")
    print("РЕЗУЛЬТАТИ СИНХРОНІЗАЦІЇ")
    print(f"{'='*80}")
    print(report.get_detailed_report())
    print(f"{'='*80}\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Використання:")
        print("  python sync_missing_vehicles.py --vins VIN1 VIN2 VIN3")
        print("  python sync_missing_vehicles.py --ids ID1 ID2 ID3")
        print("\nПриклад:")
        print("  python sync_missing_vehicles.py --vins WDB9702581L830290 WMAN44ZZ7FY328192 WMAN15ZZ3KY386051")
        sys.exit(1)
    
    if sys.argv[1] == "--vins":
        vins = sys.argv[2:]
        asyncio.run(sync_vehicles_by_vins(vins))
    elif sys.argv[1] == "--ids":
        vehicle_ids = [int(id_str) for id_str in sys.argv[2:]]
        asyncio.run(sync_vehicles_by_ids(vehicle_ids))
    else:
        print("[ERROR] Невірний аргумент. Використовуйте --vins або --ids")
        sys.exit(1)
