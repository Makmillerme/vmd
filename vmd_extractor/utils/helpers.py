#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Загальні утиліти VMD Extractor
"""

import hashlib
from email.header import decode_header


def clean_num(s):
    """
    Очищення числових значень від пробілів та заміна коми на крапку.
    
    Args:
        s: Значення для очищення (може бути str, int, float, None)
    
    Returns:
        float або оригінальне значення якщо не вдалося конвертувати
    """
    if s is None:
        return None
    s = str(s).replace(" ", "").replace("\u00A0", "").replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return s


def decode_str(s):
    """
    Декодування рядка з email заголовків.
    
    Args:
        s: Рядок для декодування
    
    Returns:
        Декодований рядок
    """
    if not s:
        return ""
    parts = decode_header(s)
    out = ""
    for part, enc in parts:
        if isinstance(part, bytes):
            try:
                out += part.decode(enc or "utf-8", errors="replace")
            except Exception:
                out += part.decode("utf-8", errors="replace")
        else:
            out += part
    return out


def sha256_bytes(b: bytes) -> str:
    """
    Обчислення SHA256 хешу для байтів.
    
    Args:
        b: Байти для хешування
    
    Returns:
        Hex-рядок SHA256 хешу
    """
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def normalize_vehicle_type(vehicle_type: str) -> str:
    """
    Нормалізує тип транспортного засобу:
    - Приводить до формату: перша літера велика, решта маленькі
    - Обрізає пробіли
    
    Args:
        vehicle_type: Тип транспортного засобу для нормалізації
    
    Returns:
        Нормалізований тип транспортного засобу
    """
    if not vehicle_type:
        return ""
    
    vehicle_type = vehicle_type.strip()
    if not vehicle_type:
        return ""
    
    # Приводимо до формату: перша літера велика, решта маленькі
    normalized = vehicle_type[0].upper() + vehicle_type[1:].lower() if len(vehicle_type) > 1 else vehicle_type.upper()
    
    return normalized





