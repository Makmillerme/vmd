#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Загальні утиліти для використання в усьому проекті.
Містить спільні функції для роботи з датами, сортування та інше,
щоб уникнути дублювання коду.
"""

from datetime import datetime
from typing import Dict, Optional, Any, Tuple
from ..config import LOCAL_TZ

def current_time_iso() -> str:
    """
    Поточний час у форматі ISO-8601 в локальному часовому поясі.
    Використовується в database.py, brief/database.py та інших місцях.
    """
    return datetime.now(LOCAL_TZ).isoformat()


def vehicle_sort_key(vehicle: Dict[str, Any]) -> Tuple[Any, ...]:
    """
    Ключ для сортування транспортних засобів.
    Сортує спочатку за датою ВМД (create_at_ccd), потім за системною датою (created_at).
    Новіші записи йдуть першими (якщо використовувати reverse=True).
    
    Args:
        vehicle: Словник з даними транспортного засобу
        
    Returns:
        Кортеж значень для порівняння
    """
    # Отримуємо дати, або мінімальну дату якщо відсутня
    ccd = vehicle.get("create_at_ccd")
    if not ccd:
        payload = vehicle.get("payload")
        if isinstance(payload, dict):
            ccd = payload.get("create_at_ccd")
            
    create_at_ccd = ccd or ""
    created_at = vehicle.get("created_at") or ""
    vehicle_id = vehicle.get("id") or 0
    
    return (create_at_ccd, created_at, vehicle_id)
