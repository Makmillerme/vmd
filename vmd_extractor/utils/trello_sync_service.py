#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Централізований сервіс для синхронізації транспортних засобів з Trello.
Використовується для усунення дублювання коду між orchestrator.py, cli/menus/trello/sync.py та scripts/update_trello_cards.py
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..config import (
    DISALLOWED_TRELLO_TYPES,
    PDF_DIR,
    TRELLO_LIST_ID,
    get_trello_label_for_vehicle_type_async,
)
from .trello_sync import sync_card_data_to_db

logger = logging.getLogger(__name__)


@dataclass
class VehicleValidationResult:
    """Результат валідації транспортного засобу"""
    is_valid: bool
    skip_reason: Optional[str] = None
    label_id: Optional[str] = None
    expected_card_name: Optional[str] = None


@dataclass
class SyncResult:
    """Результат синхронізації одного транспортного засобу"""
    vehicle_id: int
    success: bool
    card_id: Optional[str] = None
    action: Optional[str] = None  # 'created', 'updated', 'skipped', 'error'
    skip_reason: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class SyncReport:
    """Звіт про синхронізацію"""
    total: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    skipped_vehicles: List[Dict] = None
    error_vehicles: List[Dict] = None
    
    def __post_init__(self):
        if self.skipped_vehicles is None:
            self.skipped_vehicles = []
        if self.error_vehicles is None:
            self.error_vehicles = []
    
    def add_result(self, result: SyncResult):
        """Додає результат синхронізації до звіту"""
        self.total += 1
        if result.success:
            if result.action == 'created':
                self.created += 1
            elif result.action == 'updated':
                self.updated += 1
            elif result.action == 'skipped':
                self.skipped += 1
                if result.skip_reason:
                    self.skipped_vehicles.append({
                        'vehicle_id': result.vehicle_id,
                        'reason': result.skip_reason
                    })
        else:
            self.errors += 1
            self.error_vehicles.append({
                'vehicle_id': result.vehicle_id,
                'error': result.error_message
            })
    
    def get_summary(self) -> str:
        """Повертає текстове резюме звіту"""
        lines = [
            f"Всього оброблено: {self.total}",
            f"Створено: {self.created}",
            f"Оновлено: {self.updated}",
            f"Пропущено: {self.skipped}",
            f"Помилок: {self.errors}",
        ]
        return "\n".join(lines)
    
    def get_detailed_report(self) -> str:
        """Повертає детальний звіт з причинами пропуску та помилок"""
        lines = [self.get_summary()]
        
        if self.skipped_vehicles:
            lines.append(f"\nПропущені машини ({len(self.skipped_vehicles)}):")
            for vehicle in self.skipped_vehicles:
                lines.append(f"  - ID {vehicle['vehicle_id']}: {vehicle['reason']}")
        
        if self.error_vehicles:
            lines.append(f"\nПомилки ({len(self.error_vehicles)}):")
            for vehicle in self.error_vehicles:
                lines.append(f"  - ID {vehicle['vehicle_id']}: {vehicle['error']}")
        
        return "\n".join(lines)


class TrelloSyncService:
    """Централізований сервіс для синхронізації транспортних засобів з Trello"""
    
    def __init__(self, trello, database):
        """
        Args:
            trello: Екземпляр TrelloIntegration
            database: Екземпляр VMDDatabase
        """
        self.trello = trello
        self.database = database
    
    def _normalize_vehicle_data(self, vehicle: Dict) -> Dict:
        """
        Нормалізує дані vehicle для роботи з обома форматами (з payload та без).
        
        Args:
            vehicle: Словник з даними транспортного засобу
            
        Returns:
            Нормалізований словник з прямими полями на верхньому рівні
        """
        # Створюємо копію щоб не змінювати оригінал
        normalized = dict(vehicle)
        
        # Обробляємо payload якщо він є
        payload = vehicle.get("payload") or {}
        if isinstance(payload, str):
            import json
            try:
                payload = json.loads(payload) if payload else {}
            except:
                payload = {}
        
        # Додаємо поля з payload якщо вони відсутні на верхньому рівні
        if payload:
            for key in ["brand", "model", "vin", "vehicle_type", "description", 
                       "create_at_ccd", "year_calendar", "mrn", "uktzed", 
                       "producer_country", "gross_weight", "net_weight", 
                       "gross_weight_kg", "net_weight_kg", "payload_kg",
                       "engine_cm3", "seats", "power_kw", "wheel_formula",
                       "year_model", "quantity", "serial_number", "unit_human"]:
                if key not in normalized or not normalized.get(key):
                    if key in payload and payload[key]:
                        normalized[key] = payload[key]
        
        return normalized
    
    async def validate_vehicle(self, vehicle: Dict) -> VehicleValidationResult:
        """
        Валідує транспортний засіб для синхронізації з Trello.
        
        Args:
            vehicle: Словник з даними транспортного засобу (може містити payload або прямі поля)
            
        Returns:
            VehicleValidationResult з результатом валідації
        """
        # Підтримка обох форматів: з payload та без
        payload = vehicle.get("payload") or {}
        if isinstance(payload, str):
            import json
            try:
                payload = json.loads(payload) if payload else {}
            except:
                payload = {}
        
        # Отримуємо дані з прямих полів або з payload
        brand = (vehicle.get("brand") or payload.get("brand") or "").strip()
        model = (vehicle.get("model") or payload.get("model") or "").strip()
        vin = (vehicle.get("vin") or payload.get("vin") or "").strip()
        vehicle_type = (vehicle.get("vehicle_type") or payload.get("vehicle_type") or "").strip()
        
        # Перевірка на контейнер
        vehicle_type_lower = vehicle_type.lower() if vehicle_type else ""
        is_container = "контейнер" in vehicle_type_lower or "змінний кузов" in vehicle_type_lower
        
        # Валідація обов'язкових полів
        if is_container:
            if not brand and not vin:
                return VehicleValidationResult(
                    is_valid=False,
                    skip_reason="Відсутні обов'язкові поля (brand або vin для контейнера)"
                )
        else:
            if not brand or not model or not vin:
                return VehicleValidationResult(
                    is_valid=False,
                    skip_reason="Відсутні обов'язкові поля (brand, model, vin)"
                )
        
        # Перевірка заборонених типів
        if vehicle_type in DISALLOWED_TRELLO_TYPES:
            return VehicleValidationResult(
                is_valid=False,
                skip_reason=f"Заборонений тип: {vehicle_type}"
            )
        
        # Отримання мітки Trello
        label_id = None
        if vehicle_type:
            label_id = await get_trello_label_for_vehicle_type_async(vehicle_type, self.database)
            if not label_id:
                return VehicleValidationResult(
                    is_valid=False,
                    skip_reason=f"Не знайдено Trello мітку для типу '{vehicle_type}'"
                )
        
        # Формування назви картки
        if is_container:
            name_parts = []
            if brand:
                name_parts.append(brand)
            if model:
                name_parts.append(model)
            if vin:
                name_parts.append(vin)
            expected_card_name = " ".join(name_parts)
        else:
            expected_card_name = f"{brand} {model} {vin}"
        
        return VehicleValidationResult(
            is_valid=True,
            label_id=label_id,
            expected_card_name=expected_card_name
        )
    
    async def sync_vehicle(
        self,
        vehicle: Dict,
        force_create: bool = False,
    ) -> SyncResult:
        """
        Синхронізує один транспортний засіб з Trello.
        
        Args:
            vehicle: Словник з даними транспортного засобу
            force_create: Якщо True, створює нову картку навіть якщо вона вже існує
            
        Returns:
            SyncResult з результатом синхронізації
        """
        vehicle_id = vehicle.get("id")
        if not vehicle_id:
            return SyncResult(
                vehicle_id=0,
                success=False,
                action='error',
                error_message="Відсутній ID транспортного засобу"
            )
        
        try:
            # Нормалізуємо дані vehicle для роботи з обома форматами
            vehicle_normalized = self._normalize_vehicle_data(vehicle)
            
            # Валідація
            validation = await self.validate_vehicle(vehicle_normalized)
            if not validation.is_valid:
                return SyncResult(
                    vehicle_id=vehicle_id,
                    success=True,
                    action='skipped',
                    skip_reason=validation.skip_reason
                )
            
            # Отримуємо дані з нормалізованого vehicle (значення в БД можуть бути None)
            brand = (vehicle_normalized.get("brand") or "").strip()
            model = (vehicle_normalized.get("model") or "").strip()
            vin = (vehicle_normalized.get("vin") or "").strip()
            vehicle_type = (vehicle_normalized.get("vehicle_type") or "").strip()
            
            # Перевірка існуючої картки
            existing_card = await self.database.get_trello_card_by_vehicle_id(vehicle_id)
            existing_card_id = existing_card.get("trello_card_id") if existing_card else None
            
            # Очищення некоректного запису
            if existing_card and (not existing_card_id or not existing_card_id.strip()):
                await self.database.delete_trello_card_record(vehicle_id=vehicle_id)
                existing_card = None
                existing_card_id = None
            
            # Перевірка існуючої картки в Trello
            card_exists = False
            card_in_list = False
            if existing_card_id:
                card_info = await self.trello.get_card_info(existing_card_id)
                if card_info:
                    card_exists = True
                    card_list_id = card_info.get("idList", "")
                    if card_list_id == TRELLO_LIST_ID:
                        card_in_list = True
            
            # Оновлення існуючої картки
            if card_exists and card_in_list and not force_create:
                # Оновлюємо дані
                create_at_ccd = vehicle_normalized.get("create_at_ccd")
                description = (vehicle_normalized.get("description") or "").strip()
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
                    "year_calendar": vehicle_normalized.get("year_calendar"),
                }
                
                # Оновлюємо назву якщо потрібно
                current_name = (card_info.get("name") or "").strip()
                if current_name != validation.expected_card_name:
                    await self.trello.update_card(existing_card_id, name=validation.expected_card_name)
                
                # Синхронізуємо кастомні поля
                await self.trello.sync_custom_fields(existing_card_id, vehicle_data)
                
                # Синхронізуємо дані в БД
                await sync_card_data_to_db(
                    self.trello,
                    self.database,
                    vehicle_id,
                    existing_card_id,
                    TRELLO_LIST_ID,
                    vehicle_type=vehicle_type,
                )
                
                return SyncResult(
                    vehicle_id=vehicle_id,
                    success=True,
                    card_id=existing_card_id,
                    action='updated'
                )
            
            # Створення нової картки
            if not card_exists or force_create:
                # Формуємо опис
                description = (vehicle_normalized.get("description") or "").strip()
                create_at_ccd = vehicle_normalized.get("create_at_ccd")
                if create_at_ccd:
                    if description:
                        description = f"{description}\n\nДата створення ВМД: {create_at_ccd}"
                    else:
                        description = f"Дата створення ВМД: {create_at_ccd}"
                
                # Формуємо vehicle_data
                vehicle_data = {
                    "brand": brand,
                    "model": model,
                    "vin": vin,
                    "description": description,
                    "create_at_ccd": create_at_ccd,
                    "year_calendar": vehicle_normalized.get("year_calendar"),
                    "vehicle_type": vehicle_type,
                }
                
                # Формуємо PDF шлях
                pdf_path = None
                if vehicle_normalized.get("pdf_url"):
                    from ..config import PDF_DIR
                    pdf_path = PDF_DIR / Path(vehicle_normalized["pdf_url"]).name
                    if not pdf_path.exists():
                        pdf_path = None
                
                # Створюємо картку
                card_id = await self.trello.create_vehicle_card(
                    vehicle=vehicle_data,
                    pdf_path=pdf_path,
                    calculate_position=True,
                    label_ids=[validation.label_id] if validation.label_id else None,
                )
                
                if card_id:
                    # Синхронізуємо дані в БД
                    await sync_card_data_to_db(
                        self.trello,
                        self.database,
                        vehicle_id,
                        card_id,
                        TRELLO_LIST_ID,
                        vehicle_type=vehicle_type,
                    )
                    
                    return SyncResult(
                        vehicle_id=vehicle_id,
                        success=True,
                        card_id=card_id,
                        action='created'
                    )
                else:
                    return SyncResult(
                        vehicle_id=vehicle_id,
                        success=False,
                        action='error',
                        error_message="Не вдалося створити картку в Trello"
                    )
            
            # Картка існує, але в іншому списку
            return SyncResult(
                vehicle_id=vehicle_id,
                success=True,
                action='skipped',
                skip_reason="Картка існує, але в іншому списку"
            )
            
        except Exception as e:
            logger.error(f"Помилка синхронізації vehicle {vehicle_id}: {e}", exc_info=True)
            return SyncResult(
                vehicle_id=vehicle_id,
                success=False,
                action='error',
                error_message=str(e)
            )
    
    async def sync_vehicles(
        self,
        vehicles: List[Dict],
        progress_callback: Optional[callable] = None,
    ) -> SyncReport:
        """
        Синхронізує список транспортних засобів з Trello.
        
        Args:
            vehicles: Список словників з даними транспортних засобів
            progress_callback: Опціональна функція для відстеження прогресу (idx, total, result)
            
        Returns:
            SyncReport з результатами синхронізації
        """
        report = SyncReport()
        total = len(vehicles)
        
        for idx, vehicle in enumerate(vehicles, 1):
            result = await self.sync_vehicle(vehicle)
            report.add_result(result)
            
            if progress_callback:
                progress_callback(idx, total, result)
        
        return report
