#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обробка PDF файлів ВМД
"""

import os
import re
import shutil
import logging
from pathlib import Path
from typing import List, Dict

from ..config import PDF_DIR

logger = logging.getLogger(__name__)


def build_pdf_filename(record: Dict, fallback: str) -> str:
    """
    Формує назву PDF файлу на основі марки, моделі та VIN.
    
    Args:
        record: Словник з даними про транспортний засіб
        fallback: Резервна назва якщо немає даних
    
    Returns:
        Назва PDF файлу
    """
    parts = []
    for key in ("brand", "model", "vin"):
        value = record.get(key)
        if value:
            parts.append(str(value).strip())

    if parts:
        base_name = " ".join(parts)
    else:
        base_name = Path(fallback).stem or "document"

    # Замінюємо недопустимі символи для імен файлів
    base_name = re.sub(r"[\\/:*?\"<>|]", "_", base_name)
    base_name = re.sub(r"\s+", "_", base_name).strip("_")

    if not base_name:
        base_name = "document"

    return f"{base_name}.pdf"


def attach_pdf_links(parsed_data: List[Dict], processed_files: List[Dict], pdf_dir: Path = None) -> None:
    """
    Зберігає PDF файли у папку pdf та додає посилання в результати.
    Перевіряє наявність PDF перед копіюванням, щоб не перезаписувати існуючі файли.
    
    Args:
        parsed_data: Список спарсених записів
        processed_files: Список оброблених файлів з інформацією про PDF
        pdf_dir: Папка для збереження PDF (за замовчуванням з config)
    """
    if pdf_dir is None:
        pdf_dir = PDF_DIR
    
    pdf_dir.mkdir(parents=True, exist_ok=True)

    # Створюємо мапу source_file -> pdf_path
    pdf_map = {
        entry["source_file"]: entry.get("pdf_path")
        for entry in processed_files
        if entry.get("pdf_path")
    }

    for record in parsed_data:
        source_file = record.get("source_file")
        
        # Перевіряємо, чи вже є pdf_url в record і чи існує файл
        existing_pdf_url = record.get("pdf_url")
        if existing_pdf_url:
            # Перевіряємо, чи файл дійсно існує
            existing_pdf_path = pdf_dir / existing_pdf_url.replace("pdf/", "").replace("pdf\\", "")
            if existing_pdf_path.exists():
                logger.debug(f"PDF already exists for {source_file}: {existing_pdf_url}, skipping")
                continue
        
        # Якщо pdf_url немає або файл не існує, генеруємо новий
        pdf_path = pdf_map.get(source_file)

        if not pdf_path or not os.path.exists(pdf_path):
            # Якщо немає джерела PDF, залишаємо pdf_url порожнім
            if not existing_pdf_url:
                record["pdf_url"] = ""
            logger.debug(f"No PDF source for {source_file}, skipping")
            continue

        pdf_filename = build_pdf_filename(record, source_file)
        target_path = pdf_dir / pdf_filename

        # Перевіряємо, чи файл вже існує (без додавання номера)
        if target_path.exists():
            # Файл вже існує, використовуємо його без копіювання
            relative_path = Path("pdf") / target_path.name
            record["pdf_url"] = relative_path.as_posix()
            logger.debug(f"PDF already exists for {source_file}: {target_path}, reusing")
            continue

        # Якщо файл з такою назвою вже існує (з номером), шукаємо вільну назву
        stem = target_path.stem
        suffix = target_path.suffix or ".pdf"
        counter = 1
        while target_path.exists():
            target_path = pdf_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        try:
            shutil.copy2(pdf_path, target_path)
            relative_path = Path("pdf") / target_path.name
            record["pdf_url"] = relative_path.as_posix()
            logger.info(f"Saved PDF for {source_file}: {target_path}")
        except Exception as e:
            logger.error(f"Failed to copy PDF for {source_file}: {e}", exc_info=True)
            record["pdf_url"] = ""



