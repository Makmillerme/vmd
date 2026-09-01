#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для обробки вже розпакованих ВМД файлів з temp_extracted
"""

import asyncio
import os
import sys
import logging
from typing import List, Dict
from pathlib import Path

# Додаємо шлях до vmd_extractor
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vmd_extractor.core.parser import AsyncVMDParser
from vmd_extractor.core.exporter import ExcelExporter
from vmd_extractor.config import TEMP_EXTRACTED_DIR, EXTRACT_DATA_DIR, PDF_DIR
from vmd_extractor.utils.pdf_handler import attach_pdf_links, build_pdf_filename

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def find_extracted_folders(temp_extracted_dir: str) -> List[Dict]:
    """
    Знаходить всі розпаковані папки в temp_extracted та збирає інформацію про них.
    """
    temp_path = Path(temp_extracted_dir)
    if not temp_path.exists():
        logger.warning(f"Directory {temp_extracted_dir} does not exist")
        return []
    
    extracted_folders = []
    
    # Скануємо всі папки в temp_extracted
    for item in temp_path.iterdir():
        if not item.is_dir():
            continue
        
        # Шукаємо doc2.xml в папці
        doc2_path = item / "doc2.xml"
        if not doc2_path.exists():
            logger.debug(f"No doc2.xml found in {item.name}")
            continue
        
        # Шукаємо PDF файл
        pdf_path = None
        for root, dirs, files in os.walk(item):
            for file in files:
                if file.lower().endswith('.pdf') and not file.endswith('.p7s'):
                    pdf_path = os.path.join(root, file)
                    break
            if pdf_path:
                break
        
        # Визначаємо source_file з назви папки (прибираємо _unzipped)
        source_file = item.name.replace("_unzipped", "")
        
        extracted_folders.append({
            "source_file": source_file,
            "extract_dir": str(item),
            "doc2_path": str(doc2_path),
            "pdf_path": pdf_path
        })
        
        logger.debug(f"Found extracted folder: {source_file}")
    
    logger.info(f"Found {len(extracted_folders)} extracted folders with doc2.xml")
    return extracted_folders


async def process_extracted_folders():
    """Головна функція обробки розпакованих файлів"""
    logger.info("="*60)
    logger.info("VMD EXTRACTOR - Processing extracted folders")
    logger.info("="*60)
    
    temp_extracted_dir = str(TEMP_EXTRACTED_DIR)
    extract_data_dir = str(EXTRACT_DATA_DIR)
    pdf_dir = PDF_DIR
    
    results = {
        "processed": 0,
        "parsed_records": 0,
        "excel_path": None,
        "errors": []
    }
    
    try:
        # Крок 1: Знаходимо всі розпаковані папки
        logger.info("\n[STEP 1] Scanning for extracted folders...")
        extracted_folders = find_extracted_folders(temp_extracted_dir)
        results["processed"] = len(extracted_folders)
        
        if not extracted_folders:
            logger.warning("No extracted folders found, stopping")
            return results
        
        # Крок 2: Парсинг даних
        logger.info("\n[STEP 2] Parsing VMD data...")
        parser = AsyncVMDParser()
        parsed_data = await parser.parse_documents(extracted_folders)
        results["parsed_records"] = len(parsed_data)
        
        if not parsed_data:
            logger.warning("No data parsed, stopping")
            return results
        
        # Крок 3: Збереження PDF та додавання посилань
        logger.info("\n[STEP 3] Saving PDF files and enriching data...")
        attach_pdf_links(parsed_data, extracted_folders, pdf_dir)
        
        # Крок 4: Експорт в Excel
        logger.info("\n[STEP 4] Exporting to Excel...")
        exporter = ExcelExporter(extract_data_dir)
        excel_path = exporter.export_to_excel(parsed_data)
        results["excel_path"] = excel_path
        
        logger.info("\n" + "="*60)
        logger.info("VMD EXTRACTOR - Processing completed successfully!")
        logger.info("="*60)
        logger.info(f"Processed folders: {results['processed']}")
        logger.info(f"Parsed records: {results['parsed_records']}")
        logger.info(f"Excel file: {results['excel_path']}")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Processing error: {e}", exc_info=True)
        results["errors"].append(str(e))
    
    return results


async def main():
    """Головна функція"""
    print("="*60)
    print("VMD EXTRACTOR - Обробка розпакованих файлів")
    print("="*60)
    print("Джерело: vmd_extractor/data/temp_extracted")
    print("Обробка: Парсинг XML та збереження PDF")
    print("Експорт: Збереження в Excel")
    print("="*60)
    print()
    
    results = await process_extracted_folders()
    
    # Виводимо результати
    print("\n" + "="*60)
    print("РЕЗУЛЬТАТИ:")
    print("="*60)
    print(f"Оброблено папок: {results['processed']}")
    print(f"Спарсено записів: {results['parsed_records']}")
    print(f"Excel файл: {results['excel_path']}")
    
    if results['errors']:
        print(f"\nПомилки: {len(results['errors'])}")
        for error in results['errors']:
            print(f"  - {error}")
    
    print("="*60)
    
    return results


if __name__ == "__main__":
    try:
        results = asyncio.run(main())
        sys.exit(0 if results['parsed_records'] > 0 else 1)
    except KeyboardInterrupt:
        print("\n\nОперацію скасовано користувачем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nКритична помилка: {e}")
        logging.exception("Critical error")
        sys.exit(1)





