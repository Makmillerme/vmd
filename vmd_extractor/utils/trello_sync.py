#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Спільні утиліти для синхронізації Trello карток
"""

import logging
from typing import Optional, Dict, Any
from ..config import get_trello_label_for_vehicle_type_async

logger = logging.getLogger(__name__)


async def sync_card_data_to_db(
    trello,
    database,
    vehicle_id: int,
    card_id: str,
    list_id: str,
    vehicle_type: Optional[str] = None,
    max_retries: int = 3,
) -> bool:
    """
    Синхронізує повні дані картки з Trello в БД з перевіркою змін та retry механізмом.
    
    Args:
        trello: Екземпляр TrelloIntegration
        database: Екземпляр VMDDatabase
        vehicle_id: ID транспортного засобу
        card_id: ID картки Trello
        list_id: ID списку Trello
        vehicle_type: Тип транспортного засобу (опціонально)
        max_retries: Максимальна кількість спроб при помилці
    
    Returns:
        True якщо синхронізація успішна, False якщо не вдалося
    """
    for attempt in range(1, max_retries + 1):
        try:
            if not vehicle_type:
                vehicle_type = await database.get_vehicle_type_by_id(vehicle_id)
            expected_label_id = None
            if vehicle_type:
                expected_label_id = await get_trello_label_for_vehicle_type_async(vehicle_type, database)

            # Отримуємо поточні дані з БД
            existing_db_data = await database.get_trello_card_by_vehicle_id(vehicle_id)
            
            # Отримуємо повні дані з Trello
            full_data = await trello.get_full_card_data(card_id)
            if not full_data:
                logger.warning(f"Could not get full data for Trello card {card_id}")
                # Зберігаємо базову інформацію якщо її немає
                if not existing_db_data:
                    await database.save_trello_card(
                        vehicle_id=vehicle_id,
                        trello_card_id=card_id,
                        trello_list_id=list_id,
                        status="success",
                    )
                return True

            # Отримуємо поточні мітки на картці
            labels = full_data.get("labels") or []
            existing_label_ids = {lbl.get("id") for lbl in labels if isinstance(lbl, dict)}
            
            # Видаляємо ВСІ мітки окрім очікуваної
            labels_to_remove = []
            for label_id in existing_label_ids:
                if label_id != expected_label_id:
                    labels_to_remove.append(label_id)
            
            # Видаляємо старі мітки
            for old_label_id in labels_to_remove:
                removed = await trello.remove_label_from_card(card_id, old_label_id)
                if removed:
                    logger.debug(f"Removed old label {old_label_id} from card {card_id}")
            
            # Якщо очікувана мітка відсутня на картці — додаємо її
            if expected_label_id and expected_label_id not in existing_label_ids:
                added = await trello.add_label_to_card(card_id, expected_label_id)
                if added:
                    refreshed = await trello.get_full_card_data(card_id)
                    if refreshed:
                        full_data = refreshed
                        labels = full_data.get("labels") or labels
                else:
                    logger.warning(
                        "Could not add expected label %s to Trello card %s",
                        expected_label_id,
                        card_id,
                    )

            # Перевіряємо чи дані змінились
            if existing_db_data and compare_card_data(existing_db_data, full_data):
                logger.debug(f"Card {card_id} data unchanged, skipping update")
                return True

            # Отримуємо поточну позицію картки
            card_pos = full_data.get("pos")
            if card_pos is not None:
                try:
                    card_pos = float(card_pos)
                except (ValueError, TypeError):
                    card_pos = None

            # Зберігаємо всі дані в БД (оновлюємо або додаємо)
            await database.save_trello_card(
                vehicle_id=vehicle_id,
                trello_card_id=card_id,
                trello_list_id=full_data.get("idList") or list_id,
                trello_list_name=full_data.get("list_name"),
                status="success",
                card_name=full_data.get("card_name"),
                description=full_data.get("description"),
                card_pos=card_pos,
                attachments=full_data.get("attachments", []),
                media_files=full_data.get("media_files", []),
                checklists=full_data.get("checklists", []),
                comments=full_data.get("comments", []),
                labels=full_data.get("labels", []),
            )
            
            logger.debug(f"Successfully synced card {card_id} to DB (attempt {attempt})")
            return True
            
        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    f"Error syncing card {card_id} to DB (attempt {attempt}/{max_retries}): {e}. Retrying..."
                )
                import asyncio
                await asyncio.sleep(1 * attempt)  # Exponential backoff
            else:
                logger.error(f"Error syncing card data to DB after {max_retries} attempts: {e}", exc_info=True)
                # Зберігаємо базову інформацію навіть якщо синхронізація не вдалася
                try:
                    await database.save_trello_card(
                        vehicle_id=vehicle_id,
                        trello_card_id=card_id,
                        trello_list_id=list_id,
                        status="error",
                    )
                except Exception:
                    pass
                return False
    
    return False


def compare_card_data(db_data: Dict[str, Any], trello_data: Dict[str, Any]) -> bool:
    """
    Порівнює дані картки з БД та Trello.
    Повертає True якщо дані однакові (не потрібно оновлювати), False якщо потрібно оновити.
    
    Args:
        db_data: Дані з БД
        trello_data: Дані з Trello
    
    Returns:
        True якщо дані ідентичні, False якщо є відмінності
    """
    if not db_data:
        return False  # Дані відсутні в БД - потрібно додати
    
    import json
    
    # Порівнюємо основні поля
    if db_data.get("card_name") != trello_data.get("card_name"):
        return False
    if db_data.get("description") != trello_data.get("description"):
        return False
    if db_data.get("trello_list_id") != trello_data.get("idList"):
        return False
    if db_data.get("trello_list_name") != trello_data.get("list_name"):
        return False
    
    # Порівнюємо позицію (з урахуванням можливих різниць у форматі)
    db_pos = db_data.get("card_pos")
    trello_pos = trello_data.get("pos")
    if db_pos is not None and trello_pos is not None:
        try:
            if abs(float(db_pos) - float(trello_pos)) > 0.01:  # Допускаємо невелику різницю
                return False
        except (ValueError, TypeError):
            pass
    elif db_pos != trello_pos:
        return False
    
    # Порівнюємо JSON поля (нормалізуємо перед порівнянням)
    def normalize_json(value):
        if not value:
            return []
        try:
            if isinstance(value, str):
                return json.loads(value)
            return value if isinstance(value, list) else []
        except Exception:
            return []
    
    db_attachments = normalize_json(db_data.get("attachments_json"))
    trello_attachments = trello_data.get("attachments", [])
    if len(db_attachments) != len(trello_attachments):
        return False
    # Порівнюємо по ID вкладень
    db_att_ids = {att.get("id") for att in db_attachments if isinstance(att, dict)}
    trello_att_ids = {att.get("id") for att in trello_attachments if isinstance(att, dict)}
    if db_att_ids != trello_att_ids:
        return False
    
    # Порівнюємо мітки
    db_labels = normalize_json(db_data.get("labels_json"))
    trello_labels = trello_data.get("labels", [])
    db_label_ids = {lbl.get("id") for lbl in db_labels if isinstance(lbl, dict)}
    trello_label_ids = {lbl.get("id") for lbl in trello_labels if isinstance(lbl, dict)}
    if db_label_ids != trello_label_ids:
        return False
    
    return True

