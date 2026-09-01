#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль синхронізації з Trello.
"""

import logging
import aiosqlite
from datetime import date
from typing import Optional
from pathlib import Path

from vmd_extractor.config import (
    DB_PATH, TRELLO_ENABLED, DISALLOWED_TRELLO_TYPES,
    TRELLO_API_KEY, TRELLO_API_TOKEN, TRELLO_BOARD_ID, TRELLO_LIST_ID,
    get_trello_label_for_vehicle_type_async, PDF_DIR, TRELLO_DB_CARD
)
from vmd_extractor.core.database import VMDDatabase
# ExcelExporter імпортується lazy де потрібен (pandas ~380ms)
from vmd_extractor.utils.common import vehicle_sort_key
from vmd_extractor.utils.trello_sync import sync_card_data_to_db
from vmd_extractor.utils.trello_integration import TrelloIntegration
from ..utils import print_header

logger = logging.getLogger(__name__)


async def _sync_card_data_to_db(
    trello,
    db: VMDDatabase,
    vehicle_id: int,
    card_id: str,
    list_id: str,
    vehicle_type: Optional[str] = None,
):
    """
    Синхронізує повні дані картки з Trello в БД.
    Використовує спільну функцію sync_card_data_to_db з utils.trello_sync.
    """
    success = await sync_card_data_to_db(
        trello=trello,
        database=db,
        vehicle_id=vehicle_id,
        card_id=card_id,
        list_id=list_id,
        vehicle_type=vehicle_type,
        max_retries=3,
    )
    if not success:
        logger.error(f"Failed to sync card {card_id} to DB after retries")


async def _sync_all_existing_cards_from_trello(trello, db: VMDDatabase):
    """
    Синхронізує дані всіх існуючих Trello карток.
    Оновлює дані тільки якщо вони змінились в Trello.
    
    Оптимізовано: спочатку отримує список ВСІХ архівованих карток з дошки
    одним запитом, потім пропускає їх при синхронізації.
    """
    try:
        # КРОК 1: Отримуємо список архівованих карток ОДНИМ запитом
        print("  Отримання списку архівованих карток...")
        archived_card_ids = await trello.get_board_archived_card_ids()
        
        # КРОК 2: Отримуємо всі картки з БД які мають trello_card_id
        await db.initialize()
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT vehicle_id, trello_card_id, trello_list_id, is_archived
                FROM trello_cards
                WHERE trello_card_id IS NOT NULL AND trello_card_id != ''
                """
            )
            rows = await cursor.fetchall()
        
        if not rows:
            return
        
        # КРОК 3: Фільтруємо архівовані картки
        active_rows = []
        archived_count = 0
        
        for row in rows:
            card_id = row["trello_card_id"]
            if card_id in archived_card_ids:
                # Картка архівована - оновлюємо статус в БД якщо потрібно
                is_archived_db = row["is_archived"] or 0
                if not is_archived_db:
                    await db.update_trello_card_presence(
                        trello_card_id=card_id,
                        is_present=True,
                        is_archived=True,
                    )
                archived_count += 1
            else:
                active_rows.append(row)
        
        if not active_rows:
            if archived_count > 0:
                print(f"  Пропущено {archived_count} архівованих карток")
            return
        
        print(f"  Синхронізація даних {len(active_rows)} активних карток (пропущено {archived_count} архівованих)...")
        synced_count = 0
        error_count = 0
        
        # КРОК 4: Синхронізуємо тільки активні картки
        for idx, row in enumerate(active_rows, 1):
            vehicle_id = row["vehicle_id"]
            card_id = row["trello_card_id"]
            list_id = row["trello_list_id"] or TRELLO_LIST_ID
            
            try:
                # Синхронізуємо дані (метод сам перевірить чи потрібно оновлювати)
                await _sync_card_data_to_db(trello, db, vehicle_id, card_id, list_id)
                synced_count += 1
                
                if idx % 10 == 0 or idx == len(active_rows):
                    print(f"  Обробка: {idx}/{len(active_rows)} (оновлено: {synced_count}, помилок: {error_count})", end='\r')
            except Exception as e:
                logger.error(f"Error syncing card {card_id}: {e}")
                error_count += 1
        
        if synced_count > 0 or archived_count > 0 or error_count > 0:
            print(f"\n  Синхронізовано {synced_count} карток, архівованих: {archived_count}, помилок: {error_count}")
    except Exception as e:
        logger.error(f"Error syncing all existing cards: {e}", exc_info=True)


async def _cleanup_trello_cards(db: VMDDatabase, trello, show_logs: bool = True) -> int:
    """Видаляє з Trello заборонені або осиротілі картки та оновлює БД"""
    if not TRELLO_ENABLED or trello is None:
        return 0

    disallowed_cards = await db.get_trello_cards_by_vehicle_types(list(DISALLOWED_TRELLO_TYPES))
    orphan_cards = await db.get_orphan_trello_cards()

    targets = disallowed_cards + orphan_cards
    if not targets:
        return 0

    if show_logs:
        print(f"\n  Видалення {len(targets)} зайвих карток у Trello...")

    removed = 0
    processed_ids = set()
    for card in targets:
        card_id = card.get("trello_card_id")
        vehicle_id = card.get("vehicle_id")

        if card_id in processed_ids:
            continue
        if card_id:
            success = await trello.delete_card(card_id)
        else:
            success = True  # Немає card_id, але потрібно прибрати запис

        if success:
            await db.delete_trello_card_record(vehicle_id=vehicle_id, trello_card_id=card_id)
            removed += 1
            processed_ids.add(card_id)

    if show_logs and removed:
        print(f"  Видалено {removed} карток.")

    return removed


async def sync_vehicles_to_trello(date_from: Optional[date] = None, date_to: Optional[date] = None):
    """Синхронізація транспортних засобів з Trello"""
    if not TRELLO_ENABLED:
        print("  Trello інтеграція вимкнена. Увімкніть її в .env файлі.")
        return
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN:
        print("  Trello API credentials не налаштовані. Перевірте .env файл.")
        return
    
    print_header("СИНХРОНІЗАЦІЯ З TRELLO")
    
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    # Конвертуємо date в формат YYYY-MM-DD для порівняння
    date_from_str = None
    date_to_str = None
    if date_from:
        date_from_str = date_from.strftime('%Y-%m-%d')
        if date_to:
            date_to_str = date_to.strftime('%Y-%m-%d')
            print(f"  Синхронізація з діапазону: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}")
        else:
            print(f"  Синхронізація з дати: {date_from.strftime('%d.%m.%Y')}")
    else:
        print("  Синхронізація всіх несинхронізованих транспортних засобів")
    
    print("\n  Завантаження списку транспортних засобів...")
    removed_empty = await db.cleanup_empty_trello_records()
    if removed_empty:
        print(f"  Видалено {removed_empty} некоректних записів Trello (без card_id)")
    # Для ручної синхронізації перевіряємо ВСІ записи, навіть вже синхронізовані
    vehicles = await db.get_vehicles_for_trello_sync(date_from=date_from_str, date_to=date_to_str, exclude_synced=False)
    
    if not vehicles:
        print("  Немає транспортних засобів для синхронізації.")
        return
    
    print(f"  Знайдено {len(vehicles)} транспортних засобів для синхронізації.")
    print("\n  Примітка: в Trello додаються тільки vehicles з наявним vehicle_type")
    print("  (пропускаються: без vehicle_type або 'Автомобіль легковий')")
    print("  Також пропускаються vehicles без brand/model/vin")
    confirm = input("\n  Продовжити синхронізацію? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("  Синхронізацію скасовано.")
        return
    
    trello = TrelloIntegration(
        api_key=TRELLO_API_KEY,
        api_token=TRELLO_API_TOKEN,
        board_id=TRELLO_BOARD_ID,
        list_id=TRELLO_LIST_ID,
        enabled=True,
    )
    
    print(f"\n  Синхронізація...")
    print("  Фільтрація: пропускаються vehicles без brand/model/vin або з типом 'Автомобіль легковий'")
    
    # Видаляємо картки заборонених типів перед синхронізацією
    for vehicle in vehicles:
        vehicle_type = (vehicle.get("vehicle_type") or "").strip()
        if vehicle_type in DISALLOWED_TRELLO_TYPES:
            existing_card = await db.get_trello_card_by_vehicle_id(vehicle["id"])
            if existing_card and existing_card.get("trello_card_id"):
                brand = (vehicle.get("brand") or "").strip()
                model = (vehicle.get("model") or "").strip()
                vin = (vehicle.get("vin") or "").strip()
                display_name = f"{brand} {model} {vin}" if brand and model and vin else f"ID {vehicle['id']}"
                print(f"  {display_name} - заборонений тип, видаляємо картку...", end='\r')
                card_deleted = await trello.delete_card(existing_card["trello_card_id"])
                if card_deleted:
                    await db.delete_trello_card_record(vehicle_id=vehicle["id"])
    
    # Сортуємо від старіших до новіших (ascending)
    vehicles = sorted(vehicles, key=vehicle_sort_key)
    
    # Створюємо сервіс синхронізації
    from vmd_extractor.utils.trello_sync_service import TrelloSyncService
    sync_service = TrelloSyncService(trello, db)
    
    # Фільтруємо vehicles для ручної синхронізації (тільки ті, що вже мають картки)
    vehicles_with_cards = []
    for vehicle in vehicles:
        existing_card = await db.get_trello_card_by_vehicle_id(vehicle["id"])
        if existing_card and existing_card.get("trello_card_id"):
            vehicles_with_cards.append(vehicle)
    
    total = len(vehicles_with_cards)
    synced_count = 0
    error_count = 0
    
    # Синхронізуємо тільки існуючі картки (не створюємо нові)
    for idx, vehicle in enumerate(vehicles_with_cards, 1):
        brand = (vehicle.get("brand") or "").strip()
        model = (vehicle.get("model") or "").strip()
        vin = (vehicle.get("vin") or "").strip()
        display_name = f"{brand} {model} {vin}" if brand and model and vin else f"ID {vehicle['id']}"
        print(f"  [{idx}/{total}] {display_name} - синхронізуємо...", end='\r')
        
        # Використовуємо sync_service для синхронізації (він не створить нову картку якщо вона не існує)
        result = await sync_service.sync_vehicle(vehicle, force_create=False)
        if result.success and result.action in ['updated', 'skipped']:
            synced_count += 1
        elif not result.success:
            error_count += 1
    
    # Очищаємо зайві картки (заборонені типи та сироти)
    print(f"\n  Очищення зайвих карток...")
    removed = await _cleanup_trello_cards(db, trello)
    
    # Синхронізуємо дані всіх існуючих карток з Trello
    print(f"\n  Синхронізація даних всіх існуючих карток з Trello...")
    await _sync_all_existing_cards_from_trello(trello, db)
    
    # Експортуємо Excel та завантажуємо в Trello
    print(f"\n  Експорт в Excel...")
    from vmd_extractor.core.exporter import ExcelExporter  # Lazy import
    exporter = ExcelExporter(database=db)
    excel_path = exporter.export_all_tables()
    
    if excel_path:
        print(f"     Excel експортовано: {excel_path}")
        # Завантажуємо Excel в Trello
        if TRELLO_DB_CARD:
            print("     Завантаження Excel в Trello...")
            excel_file = Path(excel_path)
            if excel_file.exists():
                success = await trello.update_excel_attachment(TRELLO_DB_CARD, excel_file)
                if success:
                    print("     Excel файл оновлено в Trello")
                else:
                    print("     Увага: не вдалося завантажити Excel в Trello")
            else:
                print(f"     Увага: Excel файл не знайдено: {excel_file}")
        else:
            print("     Увага: TRELLO_DB_CARD не налаштовано, Excel не завантажено")
    else:
        print("     Увага: Excel файл не експортовано")
    
    print(f"\n\n  Синхронізацію завершено:")
    print(f"     Успішно синхронізовано/оновлено: {synced_count}")
    print(f"     Помилок: {error_count}")
    if removed > 0:
        print(f"     Видалено зайвих карток: {removed}")


__all__ = [
    'sync_vehicles_to_trello',
    '_sync_card_data_to_db',
    '_sync_all_existing_cards_from_trello',
    '_cleanup_trello_cards',
]
