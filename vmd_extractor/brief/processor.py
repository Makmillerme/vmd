#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Обробник файлів брифів (розпакування .imfx та пошук doclist.xml)
"""

import asyncio
import os
import zipfile
import shutil
import logging
from typing import Dict, Optional
from pathlib import Path

from ..config import BRIEF_TEMP_EXTRACTED_DIR

logger = logging.getLogger(__name__)


class BriefProcessor:
    """Обробник файлів брифів"""
    
    def __init__(self, temp_extract_dir: str = None):
        if temp_extract_dir is None:
            temp_extract_dir = str(BRIEF_TEMP_EXTRACTED_DIR)
        self.temp_extract_dir = temp_extract_dir
    
    async def extract_imfx(self, imfx_path: str) -> Optional[Dict]:
        """Асинхронне розпакування .imfx файлу"""
        try:
            loop = asyncio.get_event_loop()
            
            # Створюємо унікальну папку для розпакування
            filename = os.path.basename(imfx_path)
            extract_dir = os.path.join(self.temp_extract_dir, f"brief_{filename}_unzipped")
            
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
            
            # Перевіряємо наявність doclist.xml
            doclist_path = os.path.join(extract_dir, "doclist.xml")
            if not os.path.exists(doclist_path):
                logger.warning(f"doclist.xml not found in {extract_dir}")
                return None
            
            logger.debug(f"Extracted brief: {filename} -> {extract_dir}")
            
            return {
                "source_file": filename,
                "extract_dir": extract_dir,
                "doclist_path": doclist_path
            }
            
        except Exception as e:
            logger.error(f"Error extracting {imfx_path}: {e}", exc_info=True)
            return None
    
    def _extract_zip(self, zip_path: str, extract_dir: str):
        """Синхронне розпакування ZIP"""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        except Exception as e:
            logger.error(f"Error extracting ZIP {zip_path}: {e}")
            raise

