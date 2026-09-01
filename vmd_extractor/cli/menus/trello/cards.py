#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль управління Trello картками.
"""

import asyncio
import logging
from typing import List


async def _input_line(prompt: str) -> str:
    """
    Зчитує рядок з stdin у worker-потоці, щоб не блокувати asyncio event loop.
    Уникає хибного asyncio.CancelledError після blocking input() у Windows/IDE.
    """
    return (await asyncio.to_thread(input, prompt)).strip()

from vmd_extractor.config import (
    DB_PATH, TRELLO_ENABLED, TRELLO_API_KEY, TRELLO_API_TOKEN,
    TRELLO_BOARD_ID, TRELLO_LIST_ID
)
from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.utils.trello_integration import TrelloIntegration
from ..utils import print_header
from .sync import _cleanup_trello_cards

logger = logging.getLogger(__name__)


async def show_trello_stats():
    """Відображає статистику по Trello інтеграції."""
    print_header("СТАТИСТИКА TRELLO")
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    summary = await db.get_trello_summary()

    print(f"\n  Всього валідних транспортних засобів: {summary['total_valid_vehicles']}")
    print(f"  Всього карток у Trello: {summary['total_trello_cards']}")
    print(f"  Без створених карток: {summary['vehicles_without_trello']}")
    print(f"  Карток без Trello ID (помилки): {summary['failed_trello_cards']}")
    latest_sync = summary['latest_sync']
    if latest_sync:
        print(f"  Остання синхронізація: {latest_sync}")
    else:
        print("  Остання синхронізація: ще не виконувалась")


async def verify_trello_links():
    """Перевіряє відповідність між транспортними засобами та Trello карками."""
    print_header("ПЕРЕВІРКА ВІДПОВІДНОСТІ TRELLO")
    db = VMDDatabase(DB_PATH)
    await db.initialize()

    missing = await db.get_vehicles_for_trello_sync(date_from=None, exclude_synced=True)
    orphans = await db.get_orphan_trello_cards()

    print(f"\n  Транспортні засоби без Trello карток: {len(missing)}")
    preview_missing = missing[:10]
    if preview_missing:
        print("  Приклади відсутніх карток:")
        for vehicle in preview_missing:
            # Використовуємо прямі колонки БД (нова структура)
            brand = vehicle.get("brand") or ""
            model = vehicle.get("model") or ""
            vin = vehicle.get("vin") or ""
            ccd_date = vehicle.get("create_at_ccd") or ""
            print(f"    - {brand} {model} {vin} (Дата ВМД: {ccd_date})")
    else:
        print("  Усі валідні транспортні засоби вже мають картки.")

    print(f"\n  Картки Trello без відповідних записів у БД: {len(orphans)}")
    if orphans:
        print("  Приклади зайвих карток:")
        for card in orphans[:10]:
            print(f"    - Card ID: {card.get('trello_card_id', 'N/A')} (List: {card.get('trello_list_id')})")

    if TRELLO_ENABLED:
        choice = input("\n  Видалити зайві картки у Trello? (yes/no): ").strip().lower()
        if choice == "yes":
            trello = TrelloIntegration(
                api_key=TRELLO_API_KEY,
                api_token=TRELLO_API_TOKEN,
                board_id=TRELLO_BOARD_ID,
                list_id=TRELLO_LIST_ID,
                enabled=TRELLO_ENABLED,
            )
            removed = await _cleanup_trello_cards(db, trello)
            print(f"  Видалено {removed} карток.")


async def add_trello_cards_by_vins():
    """Ручне додавання карток у Trello за списком VIN"""
    print_header("ДОДАВАННЯ КАРТОК ЗА VIN")
    
    if not TRELLO_ENABLED:
        print("  Trello інтеграція вимкнена.")
        return
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN:
        print("  Trello API credentials не налаштовані.")
        return
    
    print("\n  Введіть VIN коди (по одному на рядок, порожній рядок для завершення):")
    vins = []
    while True:
        try:
            vin = await _input_line("  VIN: ")
        except EOFError:
            if not vins:
                print("  Неможливо зчитати введення: stdin закрито або неінтерактивний режим.")
                print("  Запустіть CLI з PowerShell/CMD і спробуйте знову.")
                return
            break
        except KeyboardInterrupt:
            print("\n  Скасовано.")
            return
        if not vin:
            break
        vins.append(vin.upper())
    
    if not vins:
        print("  VIN коди не введені.")
        return
    
    print(f"\n  Знайдено {len(vins)} VIN кодів.")
    try:
        confirm = (await _input_line("  Продовжити? (yes/no): ")).lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Операцію скасовано.")
        return
    if confirm != "yes":
        print("  Операцію скасовано.")
        return
    
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    vehicles = await db.get_vehicles_by_vins(vins)
    
    if not vehicles:
        print("  Не знайдено транспортних засобів з вказаними VIN кодами.")
        return
    
    print(f"\n  Знайдено {len(vehicles)} транспортних засобів.")
    
    trello = TrelloIntegration(
        api_key=TRELLO_API_KEY,
        api_token=TRELLO_API_TOKEN,
        board_id=TRELLO_BOARD_ID,
        list_id=TRELLO_LIST_ID,
        enabled=True,
    )
    
    created_count = 0
    error_count = 0
    
    for idx, vehicle in enumerate(vehicles, 1):
        # Використовуємо прямі колонки БД (нова структура)
        brand = (vehicle.get("brand") or "").strip()
        model = (vehicle.get("model") or "").strip()
        vin = (vehicle.get("vin") or "").strip()
        vehicle_type = (vehicle.get("vehicle_type") or "").strip()
        
        # Перевіряємо чи картка вже існує
        existing_card = await db.get_trello_card_by_vehicle_id(vehicle["id"])
        if existing_card and existing_card.get("trello_card_id"):
            print(f"  [{idx}/{len(vehicles)}] {brand} {model} {vin} - картка вже існує")
            continue
        
        # Перевіряємо чи не заборонений тип
        from vmd_extractor.config import DISALLOWED_TRELLO_TYPES
        if vehicle_type in DISALLOWED_TRELLO_TYPES:
            print(f"  [{idx}/{len(vehicles)}] {brand} {model} {vin} - заборонений тип")
            continue
        
        # Перевіряємо чи є мітка для типу
        from vmd_extractor.config import get_trello_label_for_vehicle_type_async
        label_id = None
        if vehicle_type:
            label_id = await get_trello_label_for_vehicle_type_async(vehicle_type, db)
            if not label_id:
                print(f"  [{idx}/{len(vehicles)}] {brand} {model} {vin} - немає мітки для типу")
                continue
        
        try:
            # Формуємо дані для створення картки (прямі колонки БД)
            description = (vehicle.get("description") or "").strip()
            create_at_ccd = vehicle.get("create_at_ccd")
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
                "vehicle_type": vehicle_type,
            }
            
            # Створюємо картку
            card_id = await trello.create_vehicle_card(
                vehicle=vehicle_data,
                pdf_path=None,
                calculate_position=True,
                label_ids=[label_id] if label_id else None,
            )
            
            if card_id:
                # Зберігаємо в БД
                from vmd_extractor.utils.trello_sync import sync_card_data_to_db
                await sync_card_data_to_db(
                    trello=trello,
                    database=db,
                    vehicle_id=vehicle["id"],
                    card_id=card_id,
                    list_id=TRELLO_LIST_ID,
                    vehicle_type=vehicle_type,
                )
                created_count += 1
                print(f"  [{idx}/{len(vehicles)}] {brand} {model} {vin} - створено")
            else:
                error_count += 1
                print(f"  [{idx}/{len(vehicles)}] {brand} {model} {vin} - помилка створення")
        except Exception as e:
            logger.error(f"Error creating card for vehicle {vehicle['id']}: {e}")
            error_count += 1
            print(f"  [{idx}/{len(vehicles)}] {brand} {model} {vin} - помилка: {e}")
    
    print(f"\n  Завершено:")
    print(f"     Створено: {created_count}")
    print(f"     Помилок: {error_count}")


__all__ = [
    'show_trello_stats',
    'verify_trello_links',
    'add_trello_cards_by_vins',
]
