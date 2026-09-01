#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль інтеграції з Trello API для автоматичного створення карток при додаванні транспортних засобів
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
from ..config import LOCAL_TZ

logger = logging.getLogger(__name__)

# Rate limits згідно з документацією Trello
# https://developer.atlassian.com/cloud/trello/guides/rest-api/rate-limits/
TRELLO_RATE_LIMIT_TOKEN = 100  # 100 requests per 10 seconds per token
TRELLO_RATE_LIMIT_KEY = 300    # 300 requests per 10 seconds per key
TRELLO_WINDOW_MS = 10000       # 10 seconds window


class TrelloIntegration:
    """Клас для роботи з Trello API з підтримкою rate limiting"""

    def __init__(
        self,
        api_key: str,
        api_token: str,
        board_id: str,
        list_id: str,
        enabled: bool = True,
    ):
        self.api_key = api_key
        self.api_token = api_token
        self.board_id = board_id
        self.list_id = list_id
        self.enabled = enabled
        self.base_url = "https://api.trello.com/1"
        self._request_times = []  # Для відстеження rate limits
        self._rate_limit_lock = asyncio.Lock()

    async def create_vehicle_card(
        self,
        vehicle: Dict,
        pdf_path: Optional[Path] = None,
        calculate_position: bool = False,
        label_ids: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Створює картку в Trello для транспортного засобу
        
        Args:
            vehicle: Словник з даними транспортного засобу (brand, model, vin, description)
            pdf_path: Шлях до PDF файлу для додавання як вкладення
            calculate_position: Якщо True, обчислює правильну позицію на основі дати create_at_ccd
            label_ids: Список ID міток Trello, які слід прив'язати до картки
            
        Returns:
            ID створеної картки або None у разі помилки
        """
        if not self.enabled:
            logger.debug("Trello integration disabled")
            return None

        if not self.api_key or not self.api_token:
            logger.warning("Trello API credentials not configured")
            return None

        try:
            # Формуємо назву картки: Марка + Модель + VIN
            # Для контейнерів (змінних кузовів) VIN вже містить serial_number (оброблено в парсері)
            brand = vehicle.get("brand", "").strip()
            model = vehicle.get("model", "").strip()
            vin = vehicle.get("vin", "").strip()
            vehicle_type = (vehicle.get("vehicle_type") or "").strip()
            
            # Для контейнерів (змінних кузовів) дозволяємо створення навіть без model або vin
            is_container = "контейнер" in vehicle_type.lower() or "змінний кузов" in vehicle_type.lower()
            
            if is_container:
                # Для контейнерів: мінімальна вимога - має бути хоча б brand або vin
                if not brand and not vin:
                    logger.warning(f"Incomplete container data for Trello card: brand={brand}, vin={vin}, serial_number={serial_number}")
                    return None
                
                # Формуємо назву тільки з наявних полів
                name_parts = []
                if brand:
                    name_parts.append(brand)
                if model:
                    name_parts.append(model)
                if vin:
                    name_parts.append(vin)
                card_name = " ".join(name_parts)
            else:
                # Для інших типів: всі три поля обов'язкові
                if not brand or not model or not vin:
                    logger.warning(f"Incomplete vehicle data for Trello card: brand={brand}, model={model}, vin={vin}, serial_number={serial_number}")
                    return None
                
                card_name = f"{brand} {model} {vin}"

            # Отримуємо опис
            description = vehicle.get("description", "").strip()
            if not description:
                description = f"Транспортний засіб: {card_name}"

            # Обчислюємо позицію якщо потрібно
            position = None
            if calculate_position:
                # Витягуємо дату create_at_ccd з опису
                import re
                date_match = re.search(r'Дата створення ВМД:\s*(\d{4}-\d{2}-\d{2})', description)
                if date_match:
                    card_date = date_match.group(1)
                    # Отримуємо всі картки зі списку
                    existing_cards = await self.get_list_cards()
                    if existing_cards:
                        position = self._calculate_card_position(existing_cards, card_date)

            # Створюємо картку
            card_id = await self._create_card(
                name=card_name,
                description=description,
                position=position,
                id_labels=label_ids,
            )

            if not card_id:
                logger.error(f"Failed to create Trello card: name='{card_name}', brand='{brand}', model='{model}', vin='{vin}'")
                return None

            # Невелика затримка для того, щоб Trello API оновив дані картки (включаючи labels)
            await asyncio.sleep(0.5)

            # Додаємо PDF файл як вкладення
            if pdf_path and pdf_path.exists():
                await self._add_attachment(card_id, pdf_path)

            # Синхронізуємо кастомні поля
            await self.sync_custom_fields(card_id, vehicle)
            
            # Перевіряємо повноту кастомних полів після синхронізації
            completeness = await self.check_custom_fields_completeness(card_id, vehicle)
            if not completeness["complete"]:
                missing = ", ".join(completeness["missing_fields"])
                logger.warning(f"Card {card_id} has missing custom fields after sync: {missing}")
                # Пробуємо синхронізувати ще раз для полів, які могли бути пропущені
                await self.sync_custom_fields(card_id, vehicle)

            # Додаємо коментар
            comment_text = f"Нове авто {card_name} додане ({datetime.now(LOCAL_TZ).strftime('%d.%m.%Y %H:%M:%S')})"
            await self._add_comment(card_id, comment_text)

            logger.info(f"Created Trello card for vehicle: {card_name}")
            return card_id

        except Exception as e:
            logger.error(f"Error creating Trello card: {e}", exc_info=True)
            return None

    async def _wait_for_rate_limit(self):
        """Чекає, якщо досягнуто rate limit"""
        async with self._rate_limit_lock:
            now = asyncio.get_event_loop().time() * 1000  # в мілісекундах
            # Видаляємо запити старші за 10 секунд
            self._request_times = [t for t in self._request_times if now - t < TRELLO_WINDOW_MS]
            
            # Якщо досягнуто ліміт, чекаємо
            if len(self._request_times) >= TRELLO_RATE_LIMIT_TOKEN:
                oldest_request = min(self._request_times)
                wait_time = (TRELLO_WINDOW_MS - (now - oldest_request)) / 1000
                if wait_time > 0:
                    logger.debug(f"Rate limit reached, waiting {wait_time:.2f} seconds")
                    await asyncio.sleep(wait_time)
                    # Оновлюємо список після очікування
                    now = asyncio.get_event_loop().time() * 1000
                    self._request_times = [t for t in self._request_times if now - t < TRELLO_WINDOW_MS]
            
            # Додаємо поточний запит
            self._request_times.append(now)

    async def _create_card(
        self,
        name: str,
        description: str,
        position: Optional[float] = None,
        id_labels: Optional[List[str]] = None,
        target_list_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Створює картку в Trello
        
        Args:
            name: Назва картки
            description: Опис картки
            position: Числове значення pos для вставки в правильне місце.
                     Якщо None, використовується "top" (додає зверху)
            id_labels: Список ID міток Trello, які слід прив'язати до картки
            target_list_id: ID списку, в який створити картку. Якщо None, використовується self.list_id
        """
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards"
        list_id_to_use = target_list_id if target_list_id else self.list_id
        auth_params = {
            "key": self.api_key,
            "token": self.api_token,
        }
        # Поля картки в тілі POST, не в URL — інакше довгий desc дає HTTP 414 (CloudFront)
        form_data = {
            "idList": list_id_to_use,
            "name": name,
            "desc": description,
        }
        if id_labels:
            filtered = [label_id.strip() for label_id in id_labels if isinstance(label_id, str) and label_id.strip()]
            if filtered:
                form_data["idLabels"] = ",".join(filtered)
        
        # Визначаємо позицію
        if position is not None:
            form_data["pos"] = str(position)
        else:
            form_data["pos"] = "top"  # За замовчуванням додаємо зверху

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=auth_params, data=form_data) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("id")
                    elif response.status == 429:
                        # Rate limit exceeded
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded: {error_msg}")
                        # Чекаємо 10 секунд перед повторною спробою
                        await asyncio.sleep(10)
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"Trello API error creating card: {response.status} - {error_text}")
                        return None
        except Exception as e:
            logger.error(f"Error calling Trello API: {e}", exc_info=True)
            return None

    async def _add_attachment(self, card_id: str, file_path: Path) -> bool:
        """Додає вкладення до картки"""
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}/attachments"
        params = {
            "key": self.api_key,
            "token": self.api_token,
        }

        try:
            # Читаємо файл синхронно (невеликі PDF файли)
            file_data = file_path.read_bytes()
            
            async with aiohttp.ClientSession() as session:
                form_data = aiohttp.FormData()
                # Визначаємо content_type залежно від розширення файлу
                content_type = "application/pdf"
                if file_path.suffix.lower() in ['.xlsx', '.xls']:
                    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                
                form_data.add_field(
                    "file",
                    file_data,
                    filename=file_path.name,
                    content_type=content_type
                )
                
                async with session.post(url, params=params, data=form_data) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        file_type = "Excel" if file_path.suffix.lower() in ['.xlsx', '.xls'] else "PDF"
                        logger.info(f"Added {file_type} attachment to Trello card {card_id}: {response_data.get('name', file_path.name)}")
                        return True
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when adding attachment: {error_msg}")
                        await asyncio.sleep(10)
                        return False
                    else:
                        error_text = await response.text()
                        logger.error(f"Trello API error adding attachment: {response.status} - {error_text}")
                        logger.error(f"File: {file_path.name}, Size: {len(file_data)} bytes, Content-Type: {content_type}")
                        return False
        except Exception as e:
            logger.warning(f"Error adding attachment to Trello card: {e}")
            return False

    async def _add_comment(self, card_id: str, text: str) -> bool:
        """Додає коментар до картки (приватний метод)"""
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}/actions/comments"
        auth_params = {
            "key": self.api_key,
            "token": self.api_token,
        }
        form_data = {"text": text}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=auth_params, data=form_data) as response:
                    if response.status == 200:
                        logger.debug(f"Added comment to Trello card {card_id}")
                        return True
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when adding comment: {error_msg}")
                        await asyncio.sleep(10)
                        return False
                    else:
                        error_text = await response.text()
                        logger.warning(f"Trello API error adding comment: {response.status} - {error_text}")
                        return False
        except Exception as e:
            logger.warning(f"Error adding comment to Trello card: {e}")
            return False
    
    async def add_comment(self, card_id: str, text: str) -> bool:
        """Публічний метод для додавання коментаря до картки"""
        return await self._add_comment(card_id, text)
    
    async def create_label(
        self,
        name: str,
        color: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Створює мітку на дошці Trello.
        
        Args:
            name: Назва мітки
            color: Колір мітки (один з: yellow, purple, blue, red, green, orange, black, sky, pink, lime, null)
                  Якщо None, використовується випадковий унікальний колір
        
        Returns:
            Dict з даними мітки (id, name, color) або None якщо помилка
        """
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/boards/{self.board_id}/labels"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "name": name,
        }
        
        if color:
            params["color"] = color
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params) as response:
                    if response.status == 200:
                        label_data = await response.json()
                        logger.info(f"Created Trello label: {name} (ID: {label_data.get('id')}, Color: {label_data.get('color')})")
                        return {
                            "id": label_data.get("id"),
                            "name": label_data.get("name"),
                            "color": label_data.get("color"),
                        }
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when creating label: {error_msg}")
                        await asyncio.sleep(10)
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"Trello API error creating label: {response.status} - {error_text}")
                        return None
        except Exception as e:
            logger.error(f"Error creating Trello label: {e}", exc_info=True)
            return None
    
    async def update_label_color(self, label_id: str, color: str) -> bool:
        """
        Оновлює колір мітки Trello.
        
        Args:
            label_id: ID мітки
            color: Новий колір мітки (один з: yellow, purple, blue, red, green, orange, black, sky, pink, lime, null)
        
        Returns:
            True якщо успішно, False якщо помилка
        """
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/labels/{label_id}"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "color": color,
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, params=params) as response:
                    if response.status == 200:
                        logger.debug(f"Updated label {label_id} color to {color}")
                        return True
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when updating label: {error_msg}")
                        await asyncio.sleep(10)
                        return False
                    else:
                        error_text = await response.text()
                        logger.error(f"Trello API error updating label: {response.status} - {error_text}")
                        return False
        except Exception as e:
            logger.error(f"Error updating Trello label color: {e}", exc_info=True)
            return False

    async def get_board_custom_fields(self) -> List[Dict]:
        """
        Отримує всі кастомні поля з дошки Trello.
        
        Returns:
            Список кастомних полів з інформацією (id, name, type, options для list типу)
        """
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/boards/{self.board_id}/customFields"
        params = {
            "key": self.api_key,
            "token": self.api_token,
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        custom_fields = await response.json()
                        return custom_fields if isinstance(custom_fields, list) else []
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting custom fields: {error_msg}")
                        await asyncio.sleep(10)
                        return []
                    else:
                        error_text = await response.text()
                        logger.error(f"Trello API error getting custom fields: {response.status} - {error_text}")
                        return []
        except Exception as e:
            logger.error(f"Error getting Trello custom fields: {e}", exc_info=True)
            return []
    
    async def get_card_custom_field_items(self, card_id: str) -> List[Dict]:
        """
        Отримує значення всіх кастомних полів для картки.
        
        Args:
            card_id: ID картки Trello
        
        Returns:
            Список значень кастомних полів з інформацією про поле та значення
        """
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}/customFieldItems"
        params = {
            "key": self.api_key,
            "token": self.api_token,
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        items = await response.json()
                        return items if isinstance(items, list) else []
                    elif response.status == 404:
                        logger.debug(f"Card {card_id} not found in Trello")
                        return []
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting custom field items: {error_msg}")
                        await asyncio.sleep(10)
                        return []
                    else:
                        error_text = await response.text()
                        logger.warning(f"Trello API error getting custom field items: {response.status} - {error_text}")
                        return []
        except Exception as e:
            logger.warning(f"Error getting custom field items from Trello card: {e}")
            return []
    
    async def set_custom_field_value(
        self,
        card_id: str,
        custom_field_id: str,
        field_type: str,
        value: any,
    ) -> bool:
        """
        Встановлює значення кастомного поля для картки.
        
        Args:
            card_id: ID картки Trello
            custom_field_id: ID кастомного поля
            field_type: Тип поля ('text', 'number', 'date', 'checkbox', 'list')
            value: Значення для встановлення
        
        Returns:
            True якщо успішно, False якщо помилка
        """
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}/customField/{custom_field_id}/item"
        params = {
            "key": self.api_key,
            "token": self.api_token,
        }
        
        # Формуємо body залежно від типу поля
        body = {}
        
        if field_type == "text":
            body = {"value": {"text": str(value) if value else ""}}
        elif field_type == "number":
            # Для number потрібно передати як рядок
            # Переконуємося що значення не None перед конвертацією
            if value is None:
                body = {"value": {"number": ""}}
            else:
                # Конвертуємо в int спочатку, щоб прибрати .0 для float значень
                try:
                    int_value = int(float(str(value)))
                    body = {"value": {"number": str(int_value)}}
                except (ValueError, TypeError):
                    body = {"value": {"number": str(value)}}
        elif field_type == "date":
            # Дата в форматі YYYY-MM-DD
            if isinstance(value, str):
                body = {"value": {"date": value}}
            else:
                body = {"value": {"date": ""}}
        elif field_type == "checkbox":
            # Checkbox: "true" або "false" як рядок
            body = {"value": {"checked": "true" if value else "false"}}
        elif field_type == "list":
            # Для list потрібен idValue (ID опції зі списку)
            if value:
                body = {"idValue": str(value)}
            else:
                body = {"idValue": None}
        else:
            logger.warning(f"Unknown custom field type: {field_type}")
            return False
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, params=params, json=body) as response:
                    if response.status == 200:
                        logger.debug(f"Set custom field {custom_field_id} value for card {card_id}")
                        return True
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when setting custom field: {error_msg}")
                        await asyncio.sleep(10)
                        return False
                    else:
                        error_text = await response.text()
                        logger.error(f"Trello API error setting custom field: {response.status} - {error_text}")
                        return False
        except Exception as e:
            logger.error(f"Error setting custom field value: {e}", exc_info=True)
            return False

    async def sync_custom_fields(self, card_id: str, vehicle: Dict) -> bool:
        """
        Синхронізує кастомні поля картки з даними транспортного засобу.
        Пропускає поле "Статус" (не оновлює його).
        
        Args:
            card_id: ID картки Trello
            vehicle: Словник з даними транспортного засобу
        
        Returns:
            True якщо синхронізація успішна, False якщо помилка
        """
        try:
            # Отримуємо всі кастомні поля дошки
            custom_fields = await self.get_board_custom_fields()
            if not custom_fields:
                logger.debug("No custom fields found on board")
                return True  # Не помилка, просто немає полів
            
            # Мапінг назв полів Trello → полів з vehicle
            field_mapping = {
                "Марка": ("brand", "text"),
                "Модель": ("model", "text"),
                "Рік виготовлення": ("year_calendar", "number"),
                "VIN": ("vin", "text"),
                "Дата створення ВМД": ("create_at_ccd", "date"),
                # "Статус" - не зачіпаємо
            }
            
            # Створюємо словник для швидкого пошуку полів за назвою
            fields_by_name = {field.get("name"): field for field in custom_fields}
            
            synced_count = 0
            skipped_count = 0
            
            for trello_field_name, (vehicle_key, field_type) in field_mapping.items():
                # Пропускаємо "Статус"
                if trello_field_name == "Статус":
                    continue
                
                # Знаходимо поле в Trello
                trello_field = fields_by_name.get(trello_field_name)
                if not trello_field:
                    logger.debug(f"Custom field '{trello_field_name}' not found on board")
                    skipped_count += 1
                    continue
                
                field_id = trello_field.get("id")
                if not field_id:
                    logger.warning(f"Custom field '{trello_field_name}' has no ID")
                    skipped_count += 1
                    continue
                
                # Отримуємо значення з vehicle
                value = vehicle.get(vehicle_key)
                
                # Для create_at_ccd, якщо немає в vehicle, пробуємо в description
                if vehicle_key == "create_at_ccd" and not value:
                    description = vehicle.get("description", "")
                    if description:
                        import re
                        date_match = re.search(r'Дата створення ВМД:\s*(\d{4}-\d{2}-\d{2})', description)
                        if date_match:
                            value = date_match.group(1)
                
                # Якщо значення порожнє, пропускаємо
                # Для number полів перевіряємо тільки на None (0 - це валідне значення)
                if field_type == "number":
                    if value is None:
                        logger.debug(f"Skipping field '{trello_field_name}' - no value in vehicle data")
                        skipped_count += 1
                        continue
                else:
                    if not value:
                        logger.debug(f"Skipping field '{trello_field_name}' - no value in vehicle data")
                        skipped_count += 1
                        continue
                
                # Встановлюємо значення
                success = await self.set_custom_field_value(
                    card_id=card_id,
                    custom_field_id=field_id,
                    field_type=field_type,
                    value=value,
                )
                
                if success:
                    synced_count += 1
                    logger.debug(f"Synced custom field '{trello_field_name}' = {value}")
                else:
                    logger.warning(f"Failed to sync custom field '{trello_field_name}'")
                    skipped_count += 1
            
            logger.info(f"Custom fields sync completed: {synced_count} synced, {skipped_count} skipped")
            return True
            
        except Exception as e:
            logger.error(f"Error syncing custom fields: {e}", exc_info=True)
            return False
    
    async def check_custom_fields_completeness(self, card_id: str, vehicle: Dict) -> Dict:
        """
        Перевіряє чи всі необхідні кастомні поля заповнені для картки.
        
        Args:
            card_id: ID картки Trello
            vehicle: Словник з даними транспортного засобу
        
        Returns:
            Dict з інформацією:
            {
                "complete": bool,  # Чи всі поля заповнені
                "missing_fields": List[str],  # Список назв полів, які відсутні
                "filled_fields": List[str],  # Список назв полів, які заповнені
                "total_required": int,  # Загальна кількість необхідних полів
            }
        """
        try:
            # Отримуємо всі кастомні поля дошки
            custom_fields = await self.get_board_custom_fields()
            if not custom_fields:
                return {
                    "complete": True,
                    "missing_fields": [],
                    "filled_fields": [],
                    "total_required": 0,
                }
            
            # Мапінг назв полів Trello → полів з vehicle
            field_mapping = {
                "Марка": ("brand", "text"),
                "Модель": ("model", "text"),
                "Рік виготовлення": ("year_calendar", "number"),
                "VIN": ("vin", "text"),
                "Дата створення ВМД": ("create_at_ccd", "date"),
            }
            
            # Отримуємо поточні значення кастомних полів картки
            current_field_items = await self.get_card_custom_field_items(card_id)
            current_fields_by_id = {item.get("idCustomField"): item for item in current_field_items}
            
            # Створюємо словник для швидкого пошуку полів за назвою
            fields_by_name = {field.get("name"): field for field in custom_fields}
            
            missing_fields = []
            filled_fields = []
            
            for trello_field_name, (vehicle_key, field_type) in field_mapping.items():
                # Пропускаємо "Статус"
                if trello_field_name == "Статус":
                    continue
                
                # Знаходимо поле в Trello
                trello_field = fields_by_name.get(trello_field_name)
                if not trello_field:
                    continue  # Поле не існує на дошці, пропускаємо
                
                field_id = trello_field.get("id")
                if not field_id:
                    continue
                
                # Перевіряємо чи поле заповнене в Trello
                field_item = current_fields_by_id.get(field_id)
                is_filled_in_trello = False
                
                if field_item:
                    # Перевіряємо значення залежно від типу поля
                    if field_type == "text":
                        value = field_item.get("value", {}).get("text", "").strip()
                        is_filled_in_trello = bool(value)
                    elif field_type == "number":
                        value = field_item.get("value", {}).get("number")
                        is_filled_in_trello = value is not None
                    elif field_type == "date":
                        value = field_item.get("value", {}).get("date")
                        is_filled_in_trello = bool(value)
                    elif field_type == "checkbox":
                        value = field_item.get("value", {}).get("checked")
                        is_filled_in_trello = value is not None
                    elif field_type == "list":
                        value = field_item.get("value", {}).get("idValue")
                        is_filled_in_trello = bool(value)
                
                # Якщо поле не заповнене в Trello, перевіряємо чи є дані в vehicle
                if not is_filled_in_trello:
                    value = vehicle.get(vehicle_key)
                    
                    # Для create_at_ccd, якщо немає в vehicle, пробуємо в description
                    if vehicle_key == "create_at_ccd" and not value:
                        description = vehicle.get("description", "")
                        if description:
                            import re
                            date_match = re.search(r'Дата створення ВМД:\s*(\d{4}-\d{2}-\d{2})', description)
                            if date_match:
                                value = date_match.group(1)
                    
                    # Перевіряємо чи є значення
                    if field_type == "number":
                        has_value = value is not None
                    else:
                        has_value = bool(value)
                    
                    if has_value:
                        # Дані є в vehicle, але не заповнені в Trello
                        missing_fields.append(trello_field_name)
                    else:
                        # Дані відсутні і в vehicle, і в Trello
                        missing_fields.append(trello_field_name)
                else:
                    # Поле заповнене в Trello
                    filled_fields.append(trello_field_name)
            
            total_required = len(field_mapping) - (1 if "Статус" in field_mapping else 0)
            is_complete = len(missing_fields) == 0
            
            return {
                "complete": is_complete,
                "missing_fields": missing_fields,
                "filled_fields": filled_fields,
                "total_required": total_required,
            }
            
        except Exception as e:
            logger.error(f"Error checking custom fields completeness: {e}", exc_info=True)
            return {
                "complete": False,
                "missing_fields": [],
                "filled_fields": [],
                "total_required": 0,
            }

    async def get_all_board_labels(self) -> List[Dict]:
        """Отримує всі мітки з дошки Trello"""
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/boards/{self.board_id}/labels"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "limit": 1000,  # Максимум міток на дошці
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        labels = await response.json()
                        return labels
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting labels: {error_msg}")
                        await asyncio.sleep(10)
                        return []
                    else:
                        error_text = await response.text()
                        logger.error(f"Trello API error getting labels: {response.status} - {error_text}")
                        return []
        except Exception as e:
            logger.error(f"Error getting Trello labels: {e}", exc_info=True)
            return []

    async def get_card_info(self, card_id: str, include_archived: bool = False) -> Optional[Dict]:
        """
        Отримує інформацію про картку з Trello.
        
        Args:
            card_id: ID картки
            include_archived: Якщо False, повертає None для архівованих карток
        """
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "fields": "name,desc,idList,pos,url,dateLastActivity,closed",  # closed = archived
            "labels": "all",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Перевіряємо чи картка архівована
                        if not include_archived and data.get("closed", False):
                            logger.debug(f"Card {card_id} is archived, skipping")
                            return None
                        return data
                    elif response.status == 404:
                        logger.debug(f"Card {card_id} not found in Trello")
                        return None
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting card info: {error_msg}")
                        await asyncio.sleep(10)
                        return None
                    else:
                        logger.warning(f"Trello API error getting card info: {response.status}")
                        return None
        except Exception as e:
            logger.warning(f"Error getting card info from Trello: {e}")
            return None

    async def get_list_info(self, list_id: str) -> Optional[Dict]:
        """Отримує інформацію про список Trello (включаючи назву)"""
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/lists/{list_id}"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "fields": "id,name,closed,idBoard",  # Отримуємо потрібні поля
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data
                    elif response.status == 404:
                        logger.debug(f"List {list_id} not found in Trello")
                        return None
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting list info: {error_msg}")
                        await asyncio.sleep(10)
                        return None
                    else:
                        logger.warning(f"Trello API error getting list info: {response.status}")
                        return None
        except Exception as e:
            logger.warning(f"Error getting list info from Trello: {e}")
            return None

    async def get_list_cards(self, list_id: Optional[str] = None) -> List[Dict]:
        """Отримує всі картки зі списку Trello"""
        await self._wait_for_rate_limit()
        
        target_list_id = list_id or self.list_id
        url = f"{self.base_url}/lists/{target_list_id}/cards"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "fields": "id,name,desc,pos,idList",  # Отримуємо тільки потрібні поля
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        cards = await response.json()
                        return cards if isinstance(cards, list) else []
                    elif response.status == 404:
                        logger.debug(f"List {target_list_id} not found in Trello")
                        return []
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting list cards: {error_msg}")
                        await asyncio.sleep(10)
                        return []
                    else:
                        logger.warning(f"Trello API error getting list cards: {response.status}")
                        return []
        except Exception as e:
            logger.warning(f"Error getting list cards from Trello: {e}")
            return []

    async def get_board_archived_card_ids(self) -> set:
        """
        Отримує ID всіх архівованих карток з дошки одним запитом.
        
        Використовується для швидкої перевірки архівованих карток на початку синхронізації
        замість перевірки кожної картки окремо.
        
        Returns:
            set: Множина ID архівованих карток
        """
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/boards/{self.board_id}/cards"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "filter": "closed",  # Тільки архівовані картки
            "fields": "id",      # Мінімальні дані - тільки ID
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        cards = await response.json()
                        archived_ids = {card["id"] for card in cards if isinstance(card, dict) and "id" in card}
                        logger.info(f"Fetched {len(archived_ids)} archived card IDs from Trello board")
                        return archived_ids
                    elif response.status == 404:
                        logger.warning(f"Board {self.board_id} not found in Trello")
                        return set()
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting archived cards: {error_msg}")
                        await asyncio.sleep(10)
                        return set()
                    else:
                        logger.warning(f"Trello API error getting archived cards: {response.status}")
                        return set()
        except Exception as e:
            logger.warning(f"Error getting archived cards from Trello: {e}")
            return set()

    def _extract_date_from_description(self, description: str) -> Optional[str]:
        """Витягує дату create_at_ccd з опису картки"""
        if not description:
            return None
        # Шукаємо "Дата створення ВМД: YYYY-MM-DD"
        import re
        match = re.search(r'Дата створення ВМД:\s*(\d{4}-\d{2}-\d{2})', description)
        if match:
            return match.group(1)
        return None

    def _calculate_card_position(self, cards: List[Dict], new_card_date: str) -> float:
        """
        Обчислює правильну позицію для нової картки на основі дати.
        Картки в Trello відсортовані від новіших до старіших (зверху вниз).
        Повертає числове значення pos для вставки в правильне місце.
        """
        if not cards:
            # Якщо список порожній, додаємо зверху
            return 0.0
        
        # Створюємо список карток з датами та позиціями
        card_data = []
        for card in cards:
            desc = card.get("desc", "")
            date_str = self._extract_date_from_description(desc)
            pos = card.get("pos", 0)
            # Конвертуємо pos в число якщо потрібно
            try:
                pos_float = float(pos) if pos else 0.0
            except (ValueError, TypeError):
                pos_float = 0.0
            
            if date_str:
                card_data.append({
                    "pos": pos_float,
                    "date": date_str,
                })
        
        if not card_data:
            # Якщо немає карток з датами, додаємо зверху
            return 0.0
        
        # Сортуємо картки по даті (від новіших до старіших) та по pos (від менших до більших)
        # Менший pos = вище в списку
        card_data.sort(key=lambda x: (x["date"], -x["pos"]), reverse=True)
        
        # Знаходимо правильну позицію для нової картки
        for idx, card_info in enumerate(card_data):
            card_date = card_info["date"]
            card_pos = card_info["pos"]
            
            if new_card_date >= card_date:
                # Нова картка новіша або рівна - вставляємо перед цією
                if idx == 0:
                    # Якщо це перша (найновіша) картка, додаємо зверху
                    # Використовуємо pos першої картки - 1, але не менше 0
                    return max(0.0, card_pos - 1.0)
                else:
                    # Вставляємо між попередньою та поточною
                    prev_pos = card_data[idx - 1]["pos"]
                    curr_pos = card_pos
                    # Якщо позиції однакові або дуже близькі, використовуємо середнє
                    if abs(prev_pos - curr_pos) < 0.1:
                        return (prev_pos + curr_pos) / 2.0
                    else:
                        return max(prev_pos, curr_pos - 0.5)
        
        # Якщо нова картка старіша за всі - додаємо в кінець
        # Використовуємо pos останньої картки + 1
        last_pos = card_data[-1]["pos"]
        return last_pos + 1.0

    async def update_card(self, card_id: str, name: Optional[str] = None, description: Optional[str] = None, list_id: Optional[str] = None, pos: Optional[str] = None) -> bool:
        """Оновлює картку в Trello"""
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}"
        params = {
            "key": self.api_key,
            "token": self.api_token,
        }
        
        data = {}
        if name is not None:
            data["name"] = name
        if description is not None:
            data["desc"] = description
        if list_id is not None:
            data["idList"] = list_id
        if pos is not None:
            data["pos"] = pos

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, params=params, json=data) as response:
                    if response.status == 200:
                        logger.debug(f"Updated Trello card {card_id}")
                        return True
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when updating card: {error_msg}")
                        await asyncio.sleep(10)
                        return False
                    else:
                        error_text = await response.text()
                        logger.warning(f"Trello API error updating card: {response.status} - {error_text}")
                        return False
        except Exception as e:
            logger.warning(f"Error updating Trello card: {e}")
            return False

    async def _get_card_attachments(self, card_id: str) -> List[Dict]:
        """Отримує список вкладень картки"""
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}/attachments"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "fields": "id,name,url,mimeType,bytes,date,isUpload",  # Отримуємо потрібні поля
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data if isinstance(data, list) else []
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting attachments: {error_msg}")
                        await asyncio.sleep(10)
                        return []
                    else:
                        logger.warning(f"Trello API error getting attachments: {response.status}")
                        return []
        except Exception as e:
            logger.warning(f"Error getting attachments from Trello card: {e}")
            return []

    async def get_card_checklists(self, card_id: str) -> List[Dict]:
        """Отримує список чек-листів картки"""
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}/checklists"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "checkItems": "all",  # Отримуємо всі елементи чек-листів
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data if isinstance(data, list) else []
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting checklists: {error_msg}")
                        await asyncio.sleep(10)
                        return []
                    else:
                        logger.warning(f"Trello API error getting checklists: {response.status}")
                        return []
        except Exception as e:
            logger.warning(f"Error getting checklists from Trello card: {e}")
            return []

    async def get_card_comments(self, card_id: str) -> List[Dict]:
        """Отримує список коментарів картки"""
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}/actions"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "filter": "commentCard",  # Тільки коментарі
            "fields": "id,type,date,data,memberCreator",  # Потрібні поля
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if isinstance(data, list):
                            # Форматуємо коментарі для зручності
                            comments = []
                            for action in data:
                                if action.get("type") == "commentCard":
                                    comment_data = action.get("data", {}).get("text", "")
                                    member = action.get("memberCreator", {})
                                    comments.append({
                                        "id": action.get("id"),
                                        "text": comment_data,
                                        "date": action.get("date"),
                                        "author": {
                                            "id": member.get("id"),
                                            "fullName": member.get("fullName"),
                                            "username": member.get("username"),
                                        } if member else None,
                                    })
                            return comments
                        return []
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting comments: {error_msg}")
                        await asyncio.sleep(10)
                        return []
                    else:
                        logger.warning(f"Trello API error getting comments: {response.status}")
                        return []
        except Exception as e:
            logger.warning(f"Error getting comments from Trello card: {e}")
            return []

    async def get_full_card_data(self, card_id: str) -> Optional[Dict]:
        """
        Отримує повну інформацію про картку з Trello:
        - Основна інформація (назва, опис, позиція, список)
        - Мітки (labels)
        - Вкладення (attachments)
        - Чек-листи (checklists)
        - Коментарі (comments)
        """
        if not self.enabled:
            return None

        # Отримуємо основну інформацію про картку
        card_info = await self.get_card_info(card_id)
        if not card_info:
            return None

        # Отримуємо ID списку та назву списку
        list_id = card_info.get("idList")
        list_name = None
        if list_id:
            list_info = await self.get_list_info(list_id)
            if list_info:
                list_name = list_info.get("name")

        # Отримуємо додаткові дані паралельно
        attachments, checklists, comments, labels = await asyncio.gather(
            self._get_card_attachments(card_id),
            self.get_card_checklists(card_id),
            self.get_card_comments(card_id),
            self.get_card_labels(card_id),
            return_exceptions=True
        )

        # Обробляємо помилки
        if isinstance(attachments, Exception):
            logger.warning(f"Error getting attachments: {attachments}")
            attachments = []
        if isinstance(checklists, Exception):
            logger.warning(f"Error getting checklists: {checklists}")
            checklists = []
        if isinstance(comments, Exception):
            logger.warning(f"Error getting comments: {comments}")
            comments = []
        if isinstance(labels, Exception):
            logger.warning(f"Error getting labels: {labels}")
            labels = []
        
        # Якщо labels не отримано через окремий endpoint, пробуємо з card_info
        if not labels:
            labels = card_info.get("labels", [])
            if labels:
                logger.debug(f"Got labels from card_info for card {card_id}: {len(labels)} labels")
        
        if labels:
            logger.debug(f"Retrieved {len(labels)} labels for card {card_id}")
        else:
            # Це нормально - картка може не мати міток, система автоматично додасть правильну
            logger.debug(f"No labels found for card {card_id} (will be added automatically if needed)")

        # Розділяємо вкладення на документи та медіа
        documents = []
        media_files = []
        
        for attachment in attachments:
            mime_type = (attachment.get("mimeType") or "").lower()
            is_upload = attachment.get("isUpload", False)
            
            attachment_data = {
                "id": attachment.get("id"),
                "name": attachment.get("name"),
                "url": attachment.get("url"),
                "mimeType": mime_type,
                "bytes": attachment.get("bytes"),
                "date": attachment.get("date"),
            }
            
            # Визначаємо тип вкладення
            if mime_type.startswith("image/") or mime_type.startswith("video/"):
                media_files.append(attachment_data)
            else:
                documents.append(attachment_data)

        return {
            "card_id": card_id,
            "card_name": card_info.get("name"),
            "description": card_info.get("desc"),
            "idList": card_info.get("idList"),
            "list_name": list_name,
            "pos": card_info.get("pos"),
            "labels": labels if labels else card_info.get("labels", []),
            "attachments": documents,
            "media_files": media_files,
            "checklists": checklists,
            "comments": comments,
            "url": card_info.get("url"),
            "dateLastActivity": card_info.get("dateLastActivity"),
        }

    async def move_card_to_list(self, card_id: str, target_list_id: str) -> bool:
        """Переміщує картку в інший список Trello"""
        if not self.enabled or not card_id or not target_list_id:
            return False

        await self._wait_for_rate_limit()
        url = f"{self.base_url}/cards/{card_id}"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "idList": target_list_id,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(url, params=params) as response:
                    if response.status in (200, 201):
                        logger.debug(f"Moved card {card_id} to list {target_list_id}")
                        return True
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when moving card: {error_msg}")
                        await asyncio.sleep(10)
                        return False
                    else:
                        error_text = await response.text()
                        logger.warning(f"Trello API error moving card: {response.status} - {error_text}")
                        return False
        except Exception as e:
            logger.warning(f"Error moving card {card_id} to list {target_list_id}: {e}")
            return False

    async def add_label_to_card(self, card_id: str, label_id: str) -> bool:
        """Додає існуючу мітку до картки Trello."""
        if not self.enabled or not card_id or not label_id:
            return False

        await self._wait_for_rate_limit()
        url = f"{self.base_url}/cards/{card_id}/idLabels"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "value": label_id,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params) as response:
                    if response.status in (200, 201):
                        logger.debug(f"Added label {label_id} to card {card_id}")
                        return True
                    elif response.status == 400 and (await response.text()).find("already exists") != -1:
                        # Лейбл вже прив'язаний
                        logger.debug(f"Label {label_id} already present on card {card_id}")
                        return True
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when adding label: {error_msg}")
                        await asyncio.sleep(10)
                        return False
                    else:
                        error_text = await response.text()
                        logger.warning(f"Trello API error adding label: {response.status} - {error_text}")
                        return False
        except Exception as e:
            logger.warning(f"Error adding label {label_id} to card {card_id}: {e}")
            return False

    async def remove_label_from_card(self, card_id: str, label_id: str) -> bool:
        """Видаляє мітку з картки Trello"""
        if not self.enabled or not card_id or not label_id:
            return False

        await self._wait_for_rate_limit()
        url = f"{self.base_url}/cards/{card_id}/idLabels/{label_id}"
        params = {
            "key": self.api_key,
            "token": self.api_token,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, params=params) as response:
                    if response.status in (200, 204):
                        logger.debug(f"Removed label {label_id} from card {card_id}")
                        return True
                    elif response.status == 404:
                        # Мітка вже видалена або не існує
                        logger.debug(f"Label {label_id} not found on card {card_id} (already removed)")
                        return True
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when removing label: {error_msg}")
                        await asyncio.sleep(10)
                        return False
                    else:
                        error_text = await response.text()
                        logger.warning(f"Trello API error removing label: {response.status} - {error_text}")
                        return False
        except Exception as e:
            logger.warning(f"Error removing label {label_id} from card {card_id}: {e}")
            return False

    async def get_card_labels(self, card_id: str) -> List[Dict]:
        """Отримує список міток (labels) картки Trello"""
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}/labels"
        params = {
            "key": self.api_key,
            "token": self.api_token,
            "fields": "id,name,color",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data if isinstance(data, list) else []
                    elif response.status == 404:
                        logger.debug(f"Card {card_id} not found in Trello")
                        return []
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when getting labels: {error_msg}")
                        await asyncio.sleep(10)
                        return []
                    else:
                        logger.warning(f"Trello API error getting labels: {response.status}")
                        return []
        except Exception as e:
            logger.warning(f"Error getting labels from Trello card: {e}")
            return []

    async def _delete_attachment(self, card_id: str, attachment_id: str) -> bool:
        """Видаляє вкладення з картки"""
        await self._wait_for_rate_limit()
        
        url = f"{self.base_url}/cards/{card_id}/attachments/{attachment_id}"
        params = {
            "key": self.api_key,
            "token": self.api_token,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, params=params) as response:
                    if response.status == 200:
                        logger.debug(f"Deleted attachment {attachment_id} from Trello card {card_id}")
                        return True
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when deleting attachment: {error_msg}")
                        await asyncio.sleep(10)
                        return False
                    else:
                        error_text = await response.text()
                        logger.warning(f"Trello API error deleting attachment: {response.status} - {error_text}")
                        return False
        except Exception as e:
            logger.warning(f"Error deleting attachment from Trello card: {e}")
            return False

    async def update_excel_attachment(self, card_id: str, excel_path: Path) -> bool:
        """
        Оновлює Excel файл як вкладення на картці Trello.
        Спочатку видаляє старі Excel вкладення, потім додає новий файл.
        """
        if not self.enabled:
            logger.debug("Trello integration is disabled. Skipping Excel upload.")
            return False

        if not excel_path.exists():
            logger.warning(f"Excel file not found: {excel_path}")
            return False

        try:
            # Отримуємо список вкладень
            logger.debug(f"Getting attachments for card {card_id}")
            attachments = await self._get_card_attachments(card_id)
            logger.debug(f"Found {len(attachments)} attachments on card")
            
            # Знаходимо та видаляємо старі Excel файли
            excel_extensions = ['.xlsx', '.xls']
            deleted_count = 0
            for attachment in attachments:
                attachment_name = attachment.get('name', '').lower()
                if any(attachment_name.endswith(ext) for ext in excel_extensions):
                    attachment_id = attachment.get('id')
                    if attachment_id:
                        logger.info(f"Deleting old Excel attachment: {attachment_name} (ID: {attachment_id})")
                        deleted = await self._delete_attachment(card_id, attachment_id)
                        if deleted:
                            deleted_count += 1
                        # Невелика затримка між видаленнями для уникнення rate limit
                        await asyncio.sleep(0.5)

            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} old Excel attachment(s)")
                # Затримка після видалення перед додаванням нового
                await asyncio.sleep(1)

            # Додаємо новий Excel файл
            file_size = excel_path.stat().st_size
            logger.info(f"Uploading Excel file to Trello card {card_id}: {excel_path.name} ({file_size} bytes)")
            success = await self._add_attachment(card_id, excel_path)
            
            if success:
                logger.info(f"Successfully updated Excel attachment on Trello card {card_id}")
            else:
                logger.error(f"Failed to upload Excel file to Trello card {card_id}")
                logger.error(f"File path: {excel_path}, Size: {file_size} bytes")
            
            return success

        except Exception as e:
            logger.error(f"Error updating Excel attachment on Trello card: {e}", exc_info=True)
            return False

    async def delete_card(self, card_id: str) -> bool:
        """Видаляє картку Trello"""
        if not self.enabled or not card_id:
            return False

        await self._wait_for_rate_limit()
        url = f"{self.base_url}/cards/{card_id}"
        params = {
            "key": self.api_key,
            "token": self.api_token,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, params=params) as response:
                    if response.status in (200, 204):
                        logger.info(f"Trello card deleted: {card_id}")
                        return True
                    elif response.status == 404:
                        logger.warning(f"Trello card not found (already deleted): {card_id}")
                        return True
                    elif response.status == 429:
                        error_data = await response.json()
                        error_msg = error_data.get("error", "Rate limit exceeded")
                        logger.warning(f"Trello rate limit exceeded when deleting card: {error_msg}")
                        await asyncio.sleep(10)
                        return False
                    else:
                        error_text = await response.text()
                        logger.warning(f"Trello API error deleting card: {response.status} - {error_text}")
                        return False
        except Exception as e:
            logger.warning(f"Error deleting Trello card {card_id}: {e}")
            return False

