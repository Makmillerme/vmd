#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль управління Trello кастомними полями.
"""

import asyncio
import json
import logging
import re
import aiosqlite

from vmd_extractor.config import (
    DB_PATH, TRELLO_ENABLED, TRELLO_API_KEY, TRELLO_API_TOKEN,
    TRELLO_BOARD_ID, TRELLO_LIST_ID
)
from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.utils.trello_integration import TrelloIntegration
from ..utils import print_header, wait_for_enter

logger = logging.getLogger(__name__)


async def sync_custom_fields_for_all_cards():
    """
    Синхронізує кастомні поля для всіх існуючих Trello карток.
    
    Оптимізовано: спочатку отримує список ВСІХ архівованих карток з дошки
    одним запитом, потім пропускає їх при синхронізації.
    """
    print_header("СИНХРОНІЗАЦІЯ КАСТОМНИХ ПОЛІВ ДЛЯ ВСІХ КАРТОК")
    
    if not TRELLO_ENABLED:
        print("  Trello інтеграція вимкнена.")
        print("  Увімкніть її в .env файлі (TRELLO_ENABLED=true)")
        input("\nНатисніть Enter для продовження...")
        return
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN or not TRELLO_BOARD_ID:
        print("  Не налаштовані Trello API credentials")
        input("\nНатисніть Enter для продовження...")
        return
    
    try:
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        # Підключаємося до Trello
        trello = TrelloIntegration(
            api_key=TRELLO_API_KEY,
            api_token=TRELLO_API_TOKEN,
            board_id=TRELLO_BOARD_ID,
            list_id=TRELLO_LIST_ID or "dummy",
        )
        
        # КРОК 1: Отримуємо список архівованих карток ОДНИМ запитом
        print("  Отримання списку архівованих карток...")
        archived_card_ids = await trello.get_board_archived_card_ids()
        
        # КРОК 2: Отримуємо всі картки з БД які мають trello_card_id
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT tc.vehicle_id, tc.trello_card_id, tc.is_archived
                FROM trello_cards tc
                WHERE tc.trello_card_id IS NOT NULL AND tc.trello_card_id != ''
                ORDER BY tc.updated_at DESC
                """
            )
            rows = await cursor.fetchall()
        
        if not rows:
            print("  Не знайдено карток Trello в БД")
            wait_for_enter()
            return
        
        # КРОК 3: Фільтруємо архівовані картки
        active_rows = []
        archived_count = 0
        
        for row in rows:
            card_id = row["trello_card_id"]
            if card_id in archived_card_ids:
                # Оновлюємо статус в БД якщо потрібно
                if not row.get("is_archived", 0):
                    await db.update_trello_card_presence(
                        trello_card_id=card_id,
                        is_present=True,
                        is_archived=True,
                    )
                archived_count += 1
            else:
                active_rows.append(row)
        
        if not active_rows:
            print(f"  Всі {archived_count} карток архівовані, немає чого синхронізувати")
            wait_for_enter()
            return
        
        print(f"\n  Знайдено {len(active_rows)} активних карток (пропущено {archived_count} архівованих)")
        print("  Ця операція може зайняти багато часу...")
        
        confirm = input("\n  Продовжити синхронізацію кастомних полів? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("  Операцію скасовано.")
            wait_for_enter()
            return
        
        synced_count = 0
        error_count = 0
        skipped_count = 0
        
        print(f"\n  Синхронізація кастомних полів для {len(active_rows)} карток...\n")
        
        # КРОК 4: Синхронізуємо тільки активні картки
        for idx, row in enumerate(active_rows, 1):
            vehicle_id = row["vehicle_id"]
            card_id = row["trello_card_id"]
            
            try:
                # Отримуємо vehicle дані з БД
                vehicle = await db.get_vehicle_by_id(vehicle_id)
                if not vehicle:
                    logger.warning(f"Vehicle {vehicle_id} not found in DB")
                    skipped_count += 1
                    continue
                
                # Використовуємо прямі колонки БД (нова структура)
                brand = (vehicle.get("brand") or "").strip()
                model = (vehicle.get("model") or "").strip()
                vin = (vehicle.get("vin") or "").strip()
                create_at_ccd = vehicle.get("create_at_ccd")
                
                description = (vehicle.get("description") or "").strip()
                if create_at_ccd:
                    if description:
                        description = f"{description}\n\nДата створення ВМД: {create_at_ccd}"
                    else:
                        description = f"Дата створення ВМД: {create_at_ccd}"
                
                vehicle_data = {
                    "brand": brand,
                    "model": model,
                    "vin": vin,
                    "description": description,
                    "create_at_ccd": create_at_ccd,
                    "year_calendar": vehicle.get("year_calendar"),
                }
                
                # Синхронізуємо кастомні поля
                success = await trello.sync_custom_fields(card_id, vehicle_data)
                
                if success:
                    synced_count += 1
                    card_name = f"{brand} {model} {vin}" if brand and model and vin else f"Card {card_id}"
                    print(f"  [{idx}/{len(active_rows)}] {card_name}", end='\r')
                else:
                    error_count += 1
                
                # Показуємо прогрес кожні 10 карток або на останній
                if idx % 10 == 0 or idx == len(active_rows):
                    print(f"  [{idx}/{len(active_rows)}] Синхронізовано: {synced_count}, Помилок: {error_count}, Пропущено: {skipped_count}")
                
            except Exception as e:
                logger.error(f"Error syncing custom fields for card {card_id}: {e}")
                error_count += 1
        
        print(f"\n  Синхронізація завершена!")
        print(f"     Синхронізовано: {synced_count}")
        print(f"     Архівованих (пропущено): {archived_count}")
        print(f"     Помилок: {error_count}")
        print(f"     Пропущено (без vehicle): {skipped_count}")
        
    except Exception as e:
        logger.error(f"Error in sync_custom_fields_for_all_cards: {e}", exc_info=True)
        print(f"\n  ❌ Помилка: {e}")
    
    input("\nНатисніть Enter для продовження...")


async def check_and_fix_custom_fields_for_all_cards():
    """
    Перевіряє та виправляє кастомні поля для всіх існуючих Trello карток.
    
    Оптимізовано: спочатку отримує список ВСІХ архівованих карток з дошки
    одним запитом, потім пропускає їх при перевірці.
    """
    print_header("ПЕРЕВІРКА ТА ВИПРАВЛЕННЯ КАСТОМНИХ ПОЛІВ ДЛЯ ВСІХ КАРТОК")
    
    if not TRELLO_ENABLED:
        print("  Trello інтеграція вимкнена.")
        input("\nНатисніть Enter для продовження...")
        return
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN or not TRELLO_BOARD_ID:
        print("  Не налаштовані Trello API credentials")
        input("\nНатисніть Enter для продовження...")
        return
    
    try:
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        # Підключаємося до Trello
        trello = TrelloIntegration(
            api_key=TRELLO_API_KEY,
            api_token=TRELLO_API_TOKEN,
            board_id=TRELLO_BOARD_ID,
            list_id=TRELLO_LIST_ID,
            enabled=True,
        )
        
        # КРОК 1: Отримуємо список архівованих карток ОДНИМ запитом
        print("  Отримання списку архівованих карток...")
        archived_card_ids = await trello.get_board_archived_card_ids()
        
        # КРОК 2: Отримуємо всі картки з БД
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT tc.trello_card_id, tc.vehicle_id, tc.is_archived
                FROM trello_cards tc
                WHERE tc.trello_card_id IS NOT NULL 
                  AND tc.trello_card_id != ''
            """)
            rows = await cursor.fetchall()
        
        if not rows:
            print("  Не знайдено карток для перевірки")
            wait_for_enter()
            return
        
        # КРОК 3: Фільтруємо архівовані картки
        active_rows = []
        archived_count = 0
        
        for row in rows:
            card_id = row["trello_card_id"]
            if card_id in archived_card_ids:
                # Оновлюємо статус в БД якщо потрібно
                if not row.get("is_archived", 0):
                    await db.update_trello_card_presence(
                        trello_card_id=card_id,
                        is_present=True,
                        is_archived=True,
                    )
                archived_count += 1
            else:
                active_rows.append(row)
        
        if not active_rows:
            print(f"  Всі {archived_count} карток архівовані, немає чого перевіряти")
            wait_for_enter()
            return
        
        print(f"\n  Знайдено {len(active_rows)} активних карток (пропущено {archived_count} архівованих)")
        print("     Буде перевірено наявність даних у кастомних полях")
        print("     Відсутні дані будуть автоматично додані")
        
        confirm = input("\n  Почати перевірку та виправлення? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("  Операцію скасовано.")
            wait_for_enter()
            return
        
        checked_count = 0
        fixed_count = 0
        already_complete_count = 0
        error_count = 0
        skipped_count = 0
        
        print("\n  Перевірка та виправлення кастомних полів...")
        print("-" * 80)
        
        # КРОК 4: Обробляємо тільки активні картки
        for idx, row in enumerate(active_rows, 1):
            card_id = row["trello_card_id"]
            vehicle_id = row["vehicle_id"]
            
            try:
                # Отримуємо дані про транспортний засіб з БД
                vehicle = await db.get_vehicle_by_id(vehicle_id)
                if not vehicle:
                    skipped_count += 1
                    continue
                
                # Використовуємо прямі колонки БД (нова структура)
                brand = (vehicle.get("brand") or "").strip()
                model = (vehicle.get("model") or "").strip()
                vin = (vehicle.get("vin") or "").strip()
                description = (vehicle.get("description") or "").strip()
                
                # Витягуємо create_at_ccd з колонки або description якщо потрібно
                create_at_ccd = vehicle.get("create_at_ccd")
                if not create_at_ccd and description:
                    date_match = re.search(r'Дата створення ВМД:\s*(\d{4}-\d{2}-\d{2})', description)
                    if date_match:
                        create_at_ccd = date_match.group(1)
                
                vehicle_data = {
                    "brand": brand,
                    "model": model,
                    "vin": vin,
                    "description": description,
                    "create_at_ccd": create_at_ccd,
                    "year_calendar": vehicle.get("year_calendar"),
                }
                
                # Перевіряємо повноту кастомних полів
                completeness = await trello.check_custom_fields_completeness(card_id, vehicle_data)
                checked_count += 1
                
                if completeness["complete"]:
                    already_complete_count += 1
                else:
                    # Є відсутні поля - синхронізуємо
                    missing = completeness["missing_fields"]
                    success = await trello.sync_custom_fields(card_id, vehicle_data)
                    if success:
                        fixed_count += 1
                        if idx % 10 == 0 or idx == len(active_rows):
                            print(f"  [{idx}/{len(active_rows)}] Виправлено: {', '.join(missing)}", end='\r')
                    else:
                        error_count += 1
                
                if idx % 10 == 0 or idx == len(active_rows):
                    print(f"  Обробка: {idx}/{len(active_rows)} (перевірено: {checked_count}, виправлено: {fixed_count}, повні: {already_complete_count}, помилок: {error_count})", end='\r')
                
                await asyncio.sleep(0.2)  # Невелика затримка для rate limiting
                
            except Exception as e:
                error_count += 1
                logger.error(f"Error processing card {card_id}: {e}")
        
        print("\n" + "=" * 80)
        print(f"  РЕЗУЛЬТАТИ:")
        print(f"     Перевірено карток: {checked_count}")
        print(f"     Виправлено карток: {fixed_count}")
        print(f"     Вже повні картки: {already_complete_count}")
        print(f"     Архівованих (пропущено): {archived_count}")
        print(f"     Пропущено (без vehicle): {skipped_count}")
        print(f"     Помилок: {error_count}")
        print("=" * 80)
        print("\n  Перевірка та виправлення завершено!")
        print("     Всі активні картки тепер мають заповнені кастомні поля.")
        
    except Exception as e:
        logger.error(f"Error in check_and_fix_custom_fields_for_all_cards: {e}", exc_info=True)
        print(f"\n  ❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНатисніть Enter для продовження...")


__all__ = [
    'sync_custom_fields_for_all_cards',
    'check_and_fix_custom_fields_for_all_cards',
]
