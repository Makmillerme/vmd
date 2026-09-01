#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для автоматичної актуалізації карток Trello на основі даних з БД.

Актуалізує:
- Назву картки (якщо змінилися brand/model/vin)
- Опис картки (якщо змінився description або create_at_ccd)
- Кастомні поля (Марка, Модель, Рік виготовлення, VIN, Дата створення ВМД)
- Мітки (якщо змінився vehicle_type)
- PDF вкладення (якщо змінився pdf_url)
- Позицію картки (якщо змінилася дата create_at_ccd)

Використання:
    python update_trello_cards.py [--dry-run] [--vehicle-id ID] [--date-from DATE] [--date-to DATE]
"""

import asyncio
import sys
import os
import logging
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Dict, List
import argparse

# Виправляємо кодування для Windows
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Додаємо кореневу директорію проекту до шляху
project_root = Path(__file__).parent.parent  # scripts -> корінь проекту
sys.path.insert(0, str(project_root))

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.config import (
    DB_PATH,
    TRELLO_ENABLED,
    TRELLO_API_KEY,
    TRELLO_API_TOKEN,
    TRELLO_BOARD_ID,
    TRELLO_LIST_ID,
)
from vmd_extractor.utils.trello_integration import TrelloIntegration
from vmd_extractor.utils.trello_sync import sync_card_data_to_db
from vmd_extractor.config import get_trello_label_for_vehicle_type_async

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def format_card_name(brand: str, model: str, vin: str, vehicle_type: str = "") -> str:
    """Формує назву картки з наявних полів (з урахуванням контейнерів)"""
    is_container = "контейнер" in (vehicle_type or "").lower() or "змінний кузов" in (vehicle_type or "").lower()
    
    if is_container:
        name_parts = []
        if brand:
            name_parts.append(brand)
        if model:
            name_parts.append(model)
        if vin:
            name_parts.append(vin)
        return " ".join(name_parts)
    else:
        if brand and model and vin:
            return f"{brand} {model} {vin}"
        return ""


async def get_vehicles_to_update(
    db: VMDDatabase,
    vehicle_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[Dict]:
    """Отримує список vehicles для актуалізації (які вже мають Trello картки)"""
    import aiosqlite
    
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        
        # Використовуємо нормалізовані колонки
        query = """
            SELECT DISTINCT v.id, v.vin, v.model, v.brand, v.vehicle_type,
                   v.create_at_ccd, v.pdf_url, v.uktzed, v.description,
                   v.producer_country, v.gross_weight, v.net_weight,
                   v.gross_weight_kg, v.net_weight_kg, v.payload_kg,
                   v.engine_cm3, v.seats, v.power_kw, v.wheel_formula,
                   v.year_model, v.year_calendar, v.quantity, v.serial_number, v.unit_human,
                   tc.trello_card_id, tc.trello_list_id, tc.card_name, tc.description as card_description
            FROM vehicles v
            INNER JOIN trello_cards tc ON v.id = tc.vehicle_id
            WHERE tc.trello_card_id IS NOT NULL 
              AND tc.trello_card_id != ''
        """
        
        params = []
        
        if vehicle_id:
            query += " AND v.id = ?"
            params.append(vehicle_id)
        
        if date_from:
            query += " AND DATE(v.create_at_ccd) >= ?"
            params.append(date_from.isoformat())
        
        if date_to:
            query += " AND DATE(v.create_at_ccd) <= ?"
            params.append(date_to.isoformat())
        
        query += " ORDER BY v.id"
        
        cursor = await conn.execute(query, tuple(params))
        rows = await cursor.fetchall()
        
        vehicles = []
        for row in rows:
            # Формуємо payload з нормалізованих колонок
            payload = {
                "vehicle_type": row["vehicle_type"],
                "brand": row["brand"],
                "model": row["model"],
                "vin": row["vin"],
                "uktzed": row["uktzed"],
                "description": row["description"],
                "producer_country": row["producer_country"],
                "gross_weight": row["gross_weight"],
                "net_weight": row["net_weight"],
                "gross_weight_kg": row["gross_weight_kg"],
                "net_weight_kg": row["net_weight_kg"],
                "payload_kg": row["payload_kg"],
                "engine_cm3": row["engine_cm3"],
                "seats": row["seats"],
                "power_kw": row["power_kw"],
                "wheel_formula": row["wheel_formula"],
                "year_model": row["year_model"],
                "year_calendar": row["year_calendar"],
                "quantity": row["quantity"],
                "serial_number": row["serial_number"],
                "unit_human": row["unit_human"],
                "create_at_ccd": row["create_at_ccd"],
            }
            
            vehicles.append({
                "id": row["id"],
                "vin": row["vin"],
                "model": row["model"],
                "create_at_ccd": row["create_at_ccd"],
                "pdf_url": row["pdf_url"],
                "payload": payload,
                "trello_card_id": row["trello_card_id"],
                "trello_list_id": row["trello_list_id"],
                "current_card_name": row["card_name"],
                "current_card_description": row["card_description"],
            })
        
        return vehicles


async def get_vehicles_to_create(
    db: VMDDatabase,
    vehicle_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> List[Dict]:
    """Отримує список vehicles для створення карток (які ще не мають Trello карток)"""
    import aiosqlite
    
    async with aiosqlite.connect(db.db_path) as conn:
        conn.row_factory = aiosqlite.Row
        
        # Використовуємо нормалізовані колонки
        query = """
            SELECT DISTINCT v.id, v.vin, v.model, v.brand, v.vehicle_type,
                   v.create_at_ccd, v.pdf_url, v.uktzed, v.description,
                   v.producer_country, v.gross_weight, v.net_weight,
                   v.gross_weight_kg, v.net_weight_kg, v.payload_kg,
                   v.engine_cm3, v.seats, v.power_kw, v.wheel_formula,
                   v.year_model, v.year_calendar, v.quantity, v.serial_number, v.unit_human
            FROM vehicles v
            LEFT JOIN trello_cards tc ON v.id = tc.vehicle_id
            WHERE (tc.trello_card_id IS NULL OR tc.trello_card_id = '')
        """
        
        params = []
        
        if vehicle_id:
            query += " AND v.id = ?"
            params.append(vehicle_id)
        
        if date_from:
            query += " AND DATE(v.create_at_ccd) >= ?"
            params.append(date_from.isoformat())
        
        if date_to:
            query += " AND DATE(v.create_at_ccd) <= ?"
            params.append(date_to.isoformat())
        
        query += " ORDER BY v.id"
        
        cursor = await conn.execute(query, tuple(params))
        rows = await cursor.fetchall()
        
        vehicles = []
        for row in rows:
            # Формуємо payload з нормалізованих колонок
            payload = {
                "vehicle_type": row["vehicle_type"],
                "brand": row["brand"],
                "model": row["model"],
                "vin": row["vin"],
                "uktzed": row["uktzed"],
                "description": row["description"],
                "producer_country": row["producer_country"],
                "gross_weight": row["gross_weight"],
                "net_weight": row["net_weight"],
                "gross_weight_kg": row["gross_weight_kg"],
                "net_weight_kg": row["net_weight_kg"],
                "payload_kg": row["payload_kg"],
                "engine_cm3": row["engine_cm3"],
                "seats": row["seats"],
                "power_kw": row["power_kw"],
                "wheel_formula": row["wheel_formula"],
                "year_model": row["year_model"],
                "year_calendar": row["year_calendar"],
                "quantity": row["quantity"],
                "serial_number": row["serial_number"],
                "unit_human": row["unit_human"],
                "create_at_ccd": row["create_at_ccd"],
            }
            
            vehicles.append({
                "id": row["id"],
                "vin": row["vin"],
                "model": row["model"],
                "create_at_ccd": row["create_at_ccd"],
                "pdf_url": row["pdf_url"],
                "payload": payload,
            })
        
        return vehicles


async def update_trello_card(
    trello: TrelloIntegration,
    db: VMDDatabase,
    vehicle: Dict,
    dry_run: bool = False,
) -> Dict:
    """
    Актуалізує одну картку Trello.
    
    Returns:
        Dict з результатами актуалізації:
        {
            "vehicle_id": int,
            "card_id": str,
            "updated": bool,
            "changes": List[str],
            "errors": List[str],
        }
    """
    vehicle_id = vehicle["id"]
    card_id = vehicle["trello_card_id"]
    payload = vehicle["payload"]
    
    result = {
        "vehicle_id": vehicle_id,
        "card_id": card_id,
        "updated": False,
        "changes": [],
        "errors": [],
    }
    
    try:
        # Отримуємо поточні дані картки з Trello
        card_info = await trello.get_card_info(card_id)
        if not card_info:
            result["errors"].append("Картка не знайдена в Trello")
            return result
        
        # Отримуємо дані vehicle
        brand = payload.get("brand", "").strip()
        model = payload.get("model", "").strip()
        vin = payload.get("vin", "").strip()
        vehicle_type = (payload.get("vehicle_type") or "").strip()
        create_at_ccd = vehicle.get("create_at_ccd") or payload.get("create_at_ccd")
        description = payload.get("description", "").strip()
        
        # Формуємо опис
        if create_at_ccd:
            if description:
                new_description = f"{description}\n\nДата створення ВМД: {create_at_ccd}"
            else:
                new_description = f"Дата створення ВМД: {create_at_ccd}"
        else:
            new_description = description
        
        # 1. Перевіряємо та оновлюємо назву картки
        expected_card_name = format_card_name(brand, model, vin, vehicle_type)
        current_card_name = card_info.get("name", "").strip()
        
        if expected_card_name and current_card_name != expected_card_name:
            if not dry_run:
                success = await trello.update_card(card_id, name=expected_card_name)
                if success:
                    result["changes"].append(f"Назва: '{current_card_name}' → '{expected_card_name}'")
                    result["updated"] = True
                else:
                    result["errors"].append(f"Не вдалося оновити назву картки")
            else:
                result["changes"].append(f"[DRY RUN] Назва: '{current_card_name}' → '{expected_card_name}'")
        
        # 2. Перевіряємо та оновлюємо опис
        current_description = card_info.get("desc", "").strip()
        if new_description != current_description:
            if not dry_run:
                success = await trello.update_card(card_id, description=new_description)
                if success:
                    result["changes"].append("Опис оновлено")
                    result["updated"] = True
                else:
                    result["errors"].append("Не вдалося оновити опис")
            else:
                result["changes"].append("[DRY RUN] Опис оновлено")
        
        # 3. Синхронізуємо кастомні поля
        vehicle_data = {
            "brand": brand,
            "model": model,
            "vin": vin,
            "description": new_description,
            "create_at_ccd": create_at_ccd,
            "year_calendar": payload.get("year_calendar"),
            "vehicle_type": vehicle_type,
        }
        
        if not dry_run:
            success = await trello.sync_custom_fields(card_id, vehicle_data)
            if success:
                result["changes"].append("Кастомні поля синхронізовано")
                result["updated"] = True
            else:
                result["errors"].append("Не вдалося синхронізувати кастомні поля")
        else:
            result["changes"].append("[DRY RUN] Кастомні поля синхронізовано")
        
        # 4. Перевіряємо та оновлюємо мітки
        if vehicle_type:
            label_id = await get_trello_label_for_vehicle_type_async(vehicle_type, db)
            if label_id:
                # Отримуємо поточні мітки
                current_labels = card_info.get("labels", [])
                current_label_ids = {label.get("id") for label in current_labels if isinstance(label, dict)}
                
                # Перевіряємо чи є правильна мітка
                if label_id not in current_label_ids:
                    # Видаляємо всі інші мітки
                    for old_label_id in current_label_ids:
                        if old_label_id != label_id:
                            if not dry_run:
                                await trello.remove_label_from_card(card_id, old_label_id)
                            result["changes"].append(f"Видалено стару мітку: {old_label_id}")
                    
                    # Додаємо правильну мітку
                    if not dry_run:
                        success = await trello.add_label_to_card(card_id, label_id)
                        if success:
                            result["changes"].append(f"Додано мітку для типу: {vehicle_type}")
                            result["updated"] = True
                        else:
                            result["errors"].append("Не вдалося додати мітку")
                    else:
                        result["changes"].append(f"[DRY RUN] Додано мітку для типу: {vehicle_type}")
        
        # 5. Перевіряємо та оновлюємо PDF вкладення
        if vehicle.get("pdf_url"):
            from vmd_extractor.config import PDF_DIR
            pdf_path = PDF_DIR / Path(vehicle["pdf_url"]).name
            
            if pdf_path.exists():
                # Перевіряємо чи є вже PDF вкладення
                attachments = await trello._get_card_attachments(card_id)
                has_pdf = any(
                    att.get("name", "").lower().endswith(".pdf")
                    for att in attachments
                )
                
                if not has_pdf:
                    if not dry_run:
                        success = await trello._add_attachment(card_id, pdf_path)
                        if success:
                            result["changes"].append("Додано PDF вкладення")
                            result["updated"] = True
                        else:
                            result["errors"].append("Не вдалося додати PDF вкладення")
                    else:
                        result["changes"].append("[DRY RUN] Додано PDF вкладення")
        
        # 6. Синхронізуємо дані картки в БД
        if not dry_run and result["updated"]:
            await sync_card_data_to_db(
                trello,
                db,
                vehicle_id,
                card_id,
                vehicle["trello_list_id"],
                vehicle_type=vehicle_type,
            )
        
    except Exception as e:
        logger.error(f"Помилка при актуалізації картки {card_id}: {e}", exc_info=True)
        result["errors"].append(f"Помилка: {str(e)}")
    
    return result


async def create_trello_card(
    trello: TrelloIntegration,
    db: VMDDatabase,
    vehicle: Dict,
    dry_run: bool = False,
) -> Dict:
    """
    Створює нову картку Trello для vehicle.
    
    Returns:
        Dict з результатами створення:
        {
            "vehicle_id": int,
            "card_id": Optional[str],
            "created": bool,
            "changes": List[str],
            "errors": List[str],
        }
    """
    vehicle_id = vehicle["id"]
    payload = vehicle["payload"]
    
    result = {
        "vehicle_id": vehicle_id,
        "card_id": None,
        "created": False,
        "changes": [],
        "errors": [],
    }
    
    try:
        # Отримуємо дані vehicle
        brand = payload.get("brand", "").strip()
        model = payload.get("model", "").strip()
        vin = payload.get("vin", "").strip()
        vehicle_type = (payload.get("vehicle_type") or "").strip()
        create_at_ccd = vehicle.get("create_at_ccd") or payload.get("create_at_ccd")
        description = payload.get("description", "").strip()
        
        # Для контейнерів (змінних кузовів) VIN вже містить serial_number (оброблено в парсері)
        
        # Перевіряємо чи не заборонений тип
        DISALLOWED_TRELLO_TYPES = {"Автомобіль легковий"}
        if vehicle_type in DISALLOWED_TRELLO_TYPES:
            result["errors"].append(f"Заборонений тип: {vehicle_type}")
            return result
        
        # Перевіряємо чи є мітка для типу
        label_id = None
        if vehicle_type:
            label_id = await get_trello_label_for_vehicle_type_async(vehicle_type, db)
            if not label_id:
                result["errors"].append(f"Немає мітки Trello для типу: {vehicle_type}")
                return result
        
        # Перевіряємо мінімальні вимоги до даних
        is_container = "контейнер" in vehicle_type.lower() or "змінний кузов" in vehicle_type.lower()
        
        if is_container:
            # Для контейнерів: мінімальна вимога - має бути хоча б brand або vin
            if not brand and not vin:
                result["errors"].append("Відсутні обов'язкові поля (brand або vin для контейнера)")
                return result
        else:
            # Для інших типів: всі три поля обов'язкові
            if not brand or not model or not vin:
                result["errors"].append("Відсутні обов'язкові поля (brand, model, vin)")
                return result
        
        # Формуємо опис
        if create_at_ccd:
            if description:
                new_description = f"{description}\n\nДата створення ВМД: {create_at_ccd}"
            else:
                new_description = f"Дата створення ВМД: {create_at_ccd}"
        else:
            new_description = description
        
        # Формуємо PDF шлях
        pdf_path = None
        if vehicle.get("pdf_url"):
            from vmd_extractor.config import PDF_DIR
            pdf_path = PDF_DIR / Path(vehicle["pdf_url"]).name
            if not pdf_path.exists():
                pdf_path = None
        
        # Формуємо vehicle_data для створення картки
        vehicle_data = {
            "brand": brand,
            "model": model,
            "vin": vin,
            "description": new_description,
            "create_at_ccd": create_at_ccd,
            "year_calendar": payload.get("year_calendar"),
            "vehicle_type": vehicle_type,
        }
        
        if not dry_run:
            # Створюємо картку в Trello
            card_id = await trello.create_vehicle_card(
                vehicle=vehicle_data,
                pdf_path=pdf_path,
                calculate_position=True,
                label_ids=[label_id] if label_id else None,
            )
            
            if card_id:
                result["card_id"] = card_id
                result["created"] = True
                result["changes"].append(f"Створено картку: {format_card_name(brand, model, vin, vehicle_type)}")
                
                # Синхронізуємо дані картки в БД
                from vmd_extractor.config import TRELLO_LIST_ID
                await sync_card_data_to_db(
                    trello,
                    db,
                    vehicle_id,
                    card_id,
                    TRELLO_LIST_ID,
                    vehicle_type=vehicle_type,
                )
            else:
                result["errors"].append("Не вдалося створити картку в Trello")
        else:
            result["changes"].append(f"[DRY RUN] Створено картку: {format_card_name(brand, model, vin, vehicle_type)}")
            result["created"] = True
        
    except Exception as e:
        logger.error(f"Помилка при створенні картки для vehicle {vehicle_id}: {e}", exc_info=True)
        result["errors"].append(f"Помилка: {str(e)}")
    
    return result


async def main():
    """Головна функція скрипта"""
    parser = argparse.ArgumentParser(
        description="Актуалізує картки Trello на основі даних з БД"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Тільки показати що буде оновлено, без реальних змін"
    )
    parser.add_argument(
        "--vehicle-id",
        type=int,
        help="Актуалізувати тільки конкретний vehicle (ID)"
    )
    parser.add_argument(
        "--date-from",
        type=str,
        help="Актуалізувати тільки vehicles з датою від (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--date-to",
        type=str,
        help="Актуалізувати тільки vehicles з датою до (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--create-missing",
        action="store_true",
        help="Створити відсутні картки для vehicles з правильними типами"
    )
    
    args = parser.parse_args()
    
    # Перевіряємо налаштування Trello
    if not TRELLO_ENABLED:
        logger.error("Trello інтеграція вимкнена в конфігурації")
        return 1
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN or not TRELLO_BOARD_ID:
        logger.error("Не налаштовані Trello API credentials")
        return 1
    
    # Парсимо дати
    date_from = None
    date_to = None
    
    if args.date_from:
        try:
            date_from = datetime.strptime(args.date_from, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"Невірний формат дати --date-from: {args.date_from} (очікується YYYY-MM-DD)")
            return 1
    
    if args.date_to:
        try:
            date_to = datetime.strptime(args.date_to, "%Y-%m-%d").date()
        except ValueError:
            logger.error(f"Невірний формат дати --date-to: {args.date_to} (очікується YYYY-MM-DD)")
            return 1
    
    # Ініціалізуємо БД та Trello
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    trello = TrelloIntegration(
        api_key=TRELLO_API_KEY,
        api_token=TRELLO_API_TOKEN,
        board_id=TRELLO_BOARD_ID,
        list_id=TRELLO_LIST_ID or "",
        enabled=True,
    )
    
    # Отримуємо список vehicles для актуалізації
    logger.info("Отримуємо список vehicles для актуалізації...")
    vehicles_to_update = await get_vehicles_to_update(
        db,
        vehicle_id=args.vehicle_id,
        date_from=date_from,
        date_to=date_to,
    )
    
    # Отримуємо список vehicles для створення (якщо потрібно)
    vehicles_to_create = []
    if args.create_missing:
        logger.info("Отримуємо список vehicles без Trello карток...")
        vehicles_to_create = await get_vehicles_to_create(
            db,
            vehicle_id=args.vehicle_id,
            date_from=date_from,
            date_to=date_to,
        )
    
    if not vehicles_to_update and not vehicles_to_create:
        logger.info("Не знайдено vehicles для обробки")
        return 0
    
    logger.info(f"Знайдено {len(vehicles_to_update)} vehicles для актуалізації")
    if args.create_missing:
        logger.info(f"Знайдено {len(vehicles_to_create)} vehicles для створення карток")
    
    if args.dry_run:
        logger.info("=" * 80)
        logger.info("РЕЖИМ ПЕРЕВІРКИ (DRY RUN) - реальні зміни не будуть виконані")
        logger.info("=" * 80)
    
    # Актуалізуємо існуючі картки
    updated_count = 0
    created_count = 0
    error_count = 0
    skipped_count = 0
    total_changes = 0
    
    if vehicles_to_update:
        logger.info(f"\nПочаток актуалізації {len(vehicles_to_update)} карток...\n")
        
        for idx, vehicle in enumerate(vehicles_to_update, 1):
            vehicle_id = vehicle["id"]
            card_id = vehicle["trello_card_id"]
            
            logger.info(f"[{idx}/{len(vehicles_to_update)}] Vehicle ID: {vehicle_id}, Card ID: {card_id}")
            
            result = await update_trello_card(trello, db, vehicle, dry_run=args.dry_run)
            
            if result["errors"]:
                error_count += 1
                logger.error(f"  Помилки: {', '.join(result['errors'])}")
            elif result["updated"] or result["changes"]:
                updated_count += 1
                total_changes += len(result["changes"])
                logger.info(f"  Оновлено: {', '.join(result['changes'])}")
            else:
                skipped_count += 1
                logger.debug(f"  Змін не виявлено")
            
            # Невелика затримка для rate limiting
            await asyncio.sleep(0.2)
    
    # Створюємо відсутні картки
    if vehicles_to_create:
        logger.info(f"\nПочаток створення {len(vehicles_to_create)} карток...\n")
        
        for idx, vehicle in enumerate(vehicles_to_create, 1):
            vehicle_id = vehicle["id"]
            payload = vehicle["payload"]
            brand = payload.get("brand", "").strip()
            model = payload.get("model", "").strip()
            vin = payload.get("vin", "").strip()
            vehicle_type = (payload.get("vehicle_type") or "").strip()
            
            display_name = format_card_name(brand, model, vin, vehicle_type) or f"Vehicle {vehicle_id}"
            logger.info(f"[{idx}/{len(vehicles_to_create)}] Vehicle ID: {vehicle_id} ({display_name})")
            
            result = await create_trello_card(trello, db, vehicle, dry_run=args.dry_run)
            
            if result["errors"]:
                error_count += 1
                logger.error(f"  Помилки: {', '.join(result['errors'])}")
            elif result["created"]:
                created_count += 1
                total_changes += len(result["changes"])
                logger.info(f"  Створено: {', '.join(result['changes'])}")
            
            # Невелика затримка для rate limiting
            await asyncio.sleep(0.2)
    
    # Виводимо підсумок
    logger.info("\n" + "=" * 80)
    logger.info("ПІДСУМОК ОБРОБКИ")
    logger.info("=" * 80)
    logger.info(f"Всього оброблено: {len(vehicles_to_update) + len(vehicles_to_create)}")
    logger.info(f"Оновлено: {updated_count}")
    logger.info(f"Створено: {created_count}")
    logger.info(f"Пропущено (без змін): {skipped_count}")
    logger.info(f"Помилок: {error_count}")
    logger.info(f"Всього змін: {total_changes}")
    
    if args.dry_run:
        logger.info("\nЦе був режим перевірки (DRY RUN). Для реальної актуалізації запустіть без --dry-run")
    
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\nОперацію перервано користувачем")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Критична помилка: {e}", exc_info=True)
        sys.exit(1)

