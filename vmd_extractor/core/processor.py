#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Асинхронний обробник ВМД файлів (розпакування та маніпуляції)
"""

import asyncio
import os
import zipfile
import shutil
import logging
from typing import Dict, Optional, List

from ..config import TEMP_EXTRACTED_DIR

logger = logging.getLogger(__name__)


class AsyncVMDProcessor:
    """Асинхронний обробник ВМД файлів"""
    
    def __init__(self, temp_extract_dir: str = None):
        if temp_extract_dir is None:
            temp_extract_dir = str(TEMP_EXTRACTED_DIR)
        self.temp_extract_dir = temp_extract_dir
        os.makedirs(temp_extract_dir, exist_ok=True)
    
    async def extract_imfx(self, imfx_path: str) -> Optional[Dict]:
        """Асинхронне розпакування .imfx файлу"""
        try:
            loop = asyncio.get_event_loop()
            
            # Створюємо унікальну папку для розпакування
            filename = os.path.basename(imfx_path)
            extract_dir = os.path.join(self.temp_extract_dir, filename + "_unzipped")
            
            # Видаляємо стару папку якщо існує (з обробкою race condition)
            if os.path.exists(extract_dir):
                try:
                    await loop.run_in_executor(None, shutil.rmtree, extract_dir)
                    # Перевіряємо чи папка дійсно видалена (захист від race condition)
                    if os.path.exists(extract_dir):
                        await asyncio.sleep(0.1)  # Коротка затримка
                        if os.path.exists(extract_dir):
                            await loop.run_in_executor(None, shutil.rmtree, extract_dir)
                except (OSError, PermissionError) as e:
                    logger.warning(f"Could not remove existing directory {extract_dir}: {e}")
            
            # Створюємо папку (exist_ok=True забезпечує безпеку при race condition)
            os.makedirs(extract_dir, exist_ok=True)
            
            # Розпакування (синхронна операція, але в executor)
            await loop.run_in_executor(
                None, self._extract_zip, imfx_path, extract_dir
            )
            
            # Перевіряємо наявність doc2.xml
            doc2_path = os.path.join(extract_dir, "doc2.xml")
            if not os.path.exists(doc2_path):
                logger.warning(f"doc2.xml not found in {extract_dir}")
                return None
            
            # Шукаємо PDF файл
            pdf_path = None
            for root, dirs, files in os.walk(extract_dir):
                for file in files:
                    if file.lower().endswith('.pdf') and not file.endswith('.p7s'):
                        pdf_path = os.path.join(root, file)
                        break
                if pdf_path:
                    break
            
            # Логування тільки для debug
            logger.debug(f"Extracted: {filename} -> {extract_dir}")
            
            return {
                "source_file": filename,
                "extract_dir": extract_dir,
                "doc2_path": doc2_path,
                "pdf_path": pdf_path
            }
            
        except Exception as e:
            logger.error(f"Error extracting {imfx_path}: {e}")
            return None
    
    def _extract_zip(self, zip_path: str, extract_dir: str):
        """Синхронне розпакування ZIP"""
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)
    
    async def process_files(self, file_paths: List[str], show_progress: bool = False) -> List[Dict]:
        """Асинхронна обробка списку файлів"""
        total = len(file_paths)
        processed_count = 0
        processed_files = []
        
        # Створюємо завдання для паралельної обробки
        tasks = [self.extract_imfx(path) for path in file_paths]
        
        # Виконуємо обробку паралельно з відстеженням прогресу
        if show_progress:
            for coro in asyncio.as_completed(tasks):
                try:
                    result = await coro
                    processed_count += 1
                    if result:
                        processed_files.append(result)
                    print(f"   Обробка: {processed_count}/{total} ({processed_count*100//total}%)", end='\r')
                except Exception as e:
                    processed_count += 1
                    logger.error(f"Processing error: {e}")
                    print(f"   Обробка: {processed_count}/{total} ({processed_count*100//total}%)", end='\r')
            print()  # Новий рядок після прогресу
        else:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Processing error: {result}")
                    continue
                if result:
                    processed_files.append(result)
        
        return processed_files
    
    async def cleanup_extracted(self, extract_dirs: List[str]):
        """Очищення розпакованих файлів"""
        loop = asyncio.get_event_loop()
        
        for extract_dir in extract_dirs:
            try:
                if os.path.exists(extract_dir):
                    await loop.run_in_executor(
                        None, shutil.rmtree, extract_dir
                    )
                    logger.debug(f"Cleaned up: {extract_dir}")
            except Exception as e:
                logger.warning(f"Error cleaning up {extract_dir}: {e}")

