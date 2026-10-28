#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Централізована конфігурація VMD Extractor
"""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Завантаження змінних з .env файлу
load_dotenv()

# ==================== IMAP Налаштування ====================
IMAP_HOST = os.environ.get("IMAP_HOST", "imap.ukr.net")
IMAP_PORT = int(os.environ.get("IMAP_PORT", 993))
IMAP_USER = os.environ.get("IMAP_USER", "your_mail@ukr.net")
IMAP_PASS = os.environ.get("IMAP_PASS", "your_imap_app_password")

# ==================== SMTP Налаштування (для розсилки) ====================
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.ukr.net")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 465))
SMTP_USER = os.environ.get("SMTP_USER", os.environ.get("IMAP_USER", ""))
SMTP_PASS = os.environ.get("SMTP_PASS", os.environ.get("IMAP_PASS", ""))
SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME", "VMD Extractor")

# Отримувачі розсилки (через кому в .env: EMAIL=dept1@example.com,dept2@example.com)
EMAIL_RECIPIENTS_RAW = os.environ.get("EMAIL", "")
EMAIL_RECIPIENTS = [e.strip() for e in EMAIL_RECIPIENTS_RAW.split(",") if e.strip()]

# Дозволені відправники ВМД
ALLOWED_SENDERS = {
    "edecl_vmd1@customs.gov.ua",
    "edecl_vmd2@customs.gov.ua",
    "edecl_vmd3@customs.gov.ua",
}

# ==================== Фільтри файлів ====================
MIN_SIZE_KB = float(os.environ.get("MIN_SIZE_KB", "280"))
MAX_SIZE_KB = float(os.environ.get("MAX_SIZE_KB", "320"))

# Затримка між завантаженнями (секунди)
DOWNLOAD_DELAY = float(os.environ.get("DOWNLOAD_DELAY", "2.0"))

# ==================== Часовий пояс ====================
LOCAL_TIMEZONE = os.environ.get("LOCAL_TIMEZONE", "Europe/Kyiv")
try:
    LOCAL_TZ = ZoneInfo(LOCAL_TIMEZONE)
except Exception:
    LOCAL_TIMEZONE = "UTC"
    LOCAL_TZ = ZoneInfo("UTC")

# ==================== Шляхи до папок ====================
# Базовий шлях проекту
BASE_DIR = Path(__file__).parent.parent

# Папки для даних
DATA_DIR = BASE_DIR / "vmd_extractor" / "data"
FILES_DIR = DATA_DIR / "files"  # Завантажені .imfx файли
EXTRACT_DATA_DIR = DATA_DIR / "extract_data"  # Excel файли
PDF_DIR = DATA_DIR / "pdf"  # PDF файли
TEMP_EXTRACTED_DIR = DATA_DIR / "temp_extracted"  # Тимчасові розпаковані
DB_DIR = DATA_DIR / "db"
DB_FILENAME = os.environ.get("VMD_DB_FILENAME", "vmd_data.sqlite3")
DB_PATH = DB_DIR / DB_FILENAME

# Папки для брифів
BRIEF_DIR = DATA_DIR / "brief"  # PDF файли брифів
BRIEF_FILES_DIR = DATA_DIR / "brief" / "files"  # Локальні .imfx файли
BRIEF_IMG_DIR = DATA_DIR / "brief" / "img"  # Тимчасові фото для конвертації
BRIEF_TEMP_EXTRACTED_DIR = DATA_DIR / "brief" / "temp_extracted"  # Тимчасові розпаковані

# ==================== Google Drive Налаштування ====================
GOOGLE_DRIVE_ENABLED = os.environ.get("GOOGLE_DRIVE_ENABLED", "false").lower() == "true"
GOOGLE_DRIVE_WEB_APP_URL = os.environ.get("GOOGLE_DRIVE_WEB_APP_URL", "")
GOOGLE_DRIVE_API_KEY = os.environ.get("GOOGLE_DRIVE_API_KEY", "")

# Папка для логів
LOG_DIR = BASE_DIR / "vmd_logs"
LOG_FILENAME = os.environ.get("VMD_LOG_FILENAME", "vmd_downloader.log")
LOG_PATH = LOG_DIR / LOG_FILENAME

# Створюємо папки якщо не існують
for dir_path in [FILES_DIR, EXTRACT_DATA_DIR, PDF_DIR, TEMP_EXTRACTED_DIR, DB_DIR, LOG_DIR, BRIEF_DIR, BRIEF_FILES_DIR, BRIEF_IMG_DIR, BRIEF_TEMP_EXTRACTED_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Для зворотної сумісності - також створюємо старі папки якщо не існують
# (для випадків коли код ще використовує старі шляхи)
LEGACY_FILES_DIR = BASE_DIR / "vmd_extractor" / "files"
LEGACY_EXTRACT_DATA_DIR = BASE_DIR / "vmd_extractor" / "extract_data"
LEGACY_PDF_DIR = BASE_DIR / "vmd_extractor" / "pdf"
LEGACY_TEMP_EXTRACTED_DIR = BASE_DIR / "vmd_extractor" / "temp_extracted"

# Скільки несинхронізованих ТЗ створювати в Trello за один auto-прогон (без фільтра дат)
TRELLO_UNSYNCED_BATCH = max(1, int(os.environ.get("VMD_TRELLO_UNSYNCED_BATCH", "40")))

# ==================== Trello Налаштування ====================
TRELLO_ENABLED = os.environ.get("TRELLO_ENABLED", "false").lower() == "true"
TRELLO_API_KEY = os.environ.get("TRELLO_API_KEY", "")
TRELLO_API_TOKEN = os.environ.get("TRELLO_API_TOKEN", "")
TRELLO_BOARD_ID = os.environ.get("TRELLO_BOARD_ID", "")
TRELLO_LIST_ID = os.environ.get("TRELLO_LIST_ID", "")
TRELLO_DB_LIST = os.environ.get("TRELLO_DB_LIST", "")
TRELLO_DB_CARD = os.environ.get("TRELLO_DB_CARD", "")
TRELLO_LABEL_CARD_ID = os.environ.get("TRELLO_LABEL_CARD_ID", "691dc89ce2565e32d845170b")

# Відповідність типів техніки до міток (можна перевизначити через .env)
# ПРИМІТКА: Статична конфігурація використовується тільки як fallback.
# Основна конфігурація зберігається в БД (таблиця trello_labels).
# Якщо мітка не знайдена в БД, повертається None (не використовується старий ID).
_TRELLO_LABEL_DEFAULTS = {
    # Старі ID видалені - використовуємо тільки БД
    # "контейнер (змінний кузов)": ("TRELLO_LABEL_CONTAINER_ID", ""),
    # "автомобіль вантажний": ("TRELLO_LABEL_TRUCK_ID", ""),
    # "сідельний тягач": ("TRELLO_LABEL_SEMITRACTOR_ID", ""),
    # "причіп контейнеровоз": ("TRELLO_LABEL_TRAILER_ID", ""),
    # "напівпричіп": ("TRELLO_LABEL_SEMITRAILER_ID", ""),
    # "інше": ("TRELLO_LABEL_OTHER_ID", ""),
}


def _normalize_vehicle_type(value: str) -> str:
    return (value or "").strip().lower()


def _resolve_label_id(env_var: str, default_value: str) -> str:
    value = os.environ.get(env_var, default_value)
    value = value.strip() if value else ""
    return value or ""


TRELLO_LABELS_BY_TYPE = {
    key: _resolve_label_id(env_var, default_id)
    for key, (env_var, default_id) in _TRELLO_LABEL_DEFAULTS.items()
}


def get_trello_label_for_vehicle_type(vehicle_type: str) -> str | None:
    """
    Повертає ID мітки Trello для заданого типу техніки (синхронна версія).
    
    Використовує тільки статичну конфігурацію для зворотної сумісності.
    Для використання БД використовуйте get_trello_label_for_vehicle_type_async().
    
    Args:
        vehicle_type: Тип техніки
    
    Returns:
        ID мітки Trello або None
    """
    if not vehicle_type:
        return None
    
    normalized = _normalize_vehicle_type(vehicle_type)
    
    # Статична конфігурація
    label_id = TRELLO_LABELS_BY_TYPE.get(normalized)
    
    # Якщо мітка не знайдена, але це тип кузова вантажного автомобіля - використовуємо fallback
    if not label_id:
        # Перевіряємо чи це тип кузова вантажного автомобіля
        cargo_body_types = [
            "фургон", "контейнеровоз", "бортовий", "тентована платформа", "тентований",
            "фургон рефрижератор", "фургон пластиковий", "фургон бортовий",
            "фургон бортовий тентований", "фургон бортовий самоскид"
        ]
        if any(cargo_type in normalized for cargo_type in cargo_body_types):
            # Для фургонів пріоритетно використовуємо мітку "фургон", якщо вона є
            if "фургон" in normalized:
                label_id = TRELLO_LABELS_BY_TYPE.get("фургон")
            # Інакше fallback на мітку "автомобіль вантажний"
            if not label_id:
                label_id = TRELLO_LABELS_BY_TYPE.get("автомобіль вантажний")
    
    return label_id or None


async def get_trello_label_for_vehicle_type_async(vehicle_type: str, database) -> str | None:
    """
    Асинхронна версія get_trello_label_for_vehicle_type для використання в async контексті.
    
    Args:
        vehicle_type: Тип техніки
        database: Об'єкт VMDDatabase для перевірки БД
    
    Returns:
        ID мітки Trello або None
    """
    if not vehicle_type or not database:
        return None
    
    normalized = _normalize_vehicle_type(vehicle_type)
    
    # ПРІОРИТЕТ 1: Шукаємо в БД
    label_id = await database.get_trello_label_id(vehicle_type)
    if label_id:
        return label_id
    
    # Маппінг тип кузова ВМД → мітка Trello: "Тентований" = "Тентована платформа"
    if normalized == "тентований":
        label_id = await database.get_trello_label_id("Тентована платформа")
        if label_id:
            return label_id
    
    # ПРІОРИТЕТ 2: Статична конфігурація (зазвичай порожня, використовується тільки БД)
    label_id = TRELLO_LABELS_BY_TYPE.get(normalized)
    
    # Fallback для типів кузова вантажного автомобіля
    if not label_id:
        cargo_body_types = [
            "фургон", "контейнеровоз", "бортовий", "тентована платформа", "тентований",
            "фургон рефрижератор", "фургон пластиковий", "фургон бортовий",
            "фургон бортовий тентований", "фургон бортовий самоскид"
        ]
        normalized_lower = normalized.lower()
        if any(cargo_type in normalized_lower for cargo_type in cargo_body_types):
            # Для фургонів пріоритетно використовуємо мітку "Фургон", якщо вона є
            if "фургон" in normalized_lower:
                label_id = await database.get_trello_label_id("Фургон")
            # Інакше fallback на мітку "Автомобіль вантажний"
            if not label_id:
                label_id = await database.get_trello_label_id("Автомобіль вантажний")
    
    return label_id or None


# Типи транспортних засобів, які не повинні бути синхронізовані з Trello
DISALLOWED_TRELLO_TYPES = frozenset({"Автомобіль легковий"})


