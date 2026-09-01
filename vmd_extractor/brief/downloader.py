#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Завантажувач файлів брифів (локальні файли та Google Drive)
"""

import os
import asyncio
import logging
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime

from .google_drive import GoogleDriveIntegration
from ..config import BRIEF_FILES_DIR, LOCAL_TZ, GOOGLE_DRIVE_ENABLED
from ..utils.helpers import sha256_bytes

logger = logging.getLogger(__name__)


class BriefDownloader:
    """Завантажувач файлів брифів (локальні файли та Google Drive)"""
    
    def __init__(
        self,
        save_dir: str = None,
        google_drive: Optional[GoogleDriveIntegration] = None,
        brief_database = None
    ):
        """
        Args:
            save_dir: Папка для збереження файлів (за замовчуванням BRIEF_FILES_DIR)
            google_drive: Екземпляр GoogleDriveIntegration (якщо None, створюється новий якщо увімкнено)
            brief_database: Екземпляр BriefDatabase для перевірки дублікатів
        """
        if save_dir is None:
            save_dir = str(BRIEF_FILES_DIR)
        self.save_dir = save_dir
        
        # Створюємо папку якщо не існує
        Path(save_dir).mkdir(parents=True, exist_ok=True)
        
        # Ініціалізуємо Google Drive якщо увімкнено
        if GOOGLE_DRIVE_ENABLED:
            try:
                self.google_drive = google_drive or GoogleDriveIntegration()
            except (ValueError, ImportError) as e:
                logger.warning(f"Google Drive integration is enabled but not configured: {e}")
                self.google_drive = None
        else:
            self.google_drive = None
        
        # База даних для перевірки дублікатів
        self.brief_database = brief_database
    
    def get_downloaded_files(self) -> List[Dict]:
        """
        Отримує список завантажених файлів з локальної папки
        
        Returns:
            Список словників з інформацією про файли
        """
        files = []
        
        try:
            for file_path in Path(self.save_dir).glob("*.imfx"):
                try:
                    file_stat = file_path.stat()
                    with open(file_path, 'rb') as f:
                        file_hash = sha256_bytes(f.read())
                    
                    files.append({
                        'filename': file_path.name,
                        'local_path': str(file_path),
                        'sha256': file_hash,
                        'size_kb': file_stat.st_size / 1024.0,
                        'modified_at': datetime.fromtimestamp(file_stat.st_mtime, LOCAL_TZ).isoformat()
                    })
                except Exception as e:
                    logger.warning(f"Error reading file {file_path}: {e}")
                    continue
            
        except Exception as e:
            logger.error(f"Error listing downloaded files: {e}", exc_info=True)
        
        return files
    
    async def download_from_google_drive(
        self,
        file_extensions: List[str] = None,
        use_api: bool = False,
        status_filter: Optional[str] = None,
        max_concurrent: int = 5,
        skip_duplicates: bool = True
    ) -> List[Dict]:
        """
        Завантажує файли брифів з Google Drive з перевіркою дублікатів та асинхронним завантаженням
        
        Args:
            file_extensions: Список розширень файлів для завантаження (за замовчуванням ['.imfx'])
            use_api: Якщо True - використовує API (з оновленням статусу), якщо False - пряме завантаження
            status_filter: Фільтр по статусу ('PENDING', 'DOWNLOADED', 'PROCESSED') - тільки для API
            max_concurrent: Максимальна кількість одночасних завантажень (за замовчуванням 5)
            skip_duplicates: Пропускати файли які вже оброблені (за замовчуванням True)
        
        Returns:
            Список словників з інформацією про завантажені файли
        """
        if not self.google_drive:
            logger.error("Google Drive integration is not enabled")
            return []
        
        if file_extensions is None:
            file_extensions = ['.imfx']
        
        downloaded_files = []
        
        try:
            # Отримуємо список файлів
            logger.info("Listing files from Google Drive...")
            files = await self.google_drive.list_files()
            
            if not files:
                logger.info("No files found in Google Drive")
                return downloaded_files
            
            # Фільтруємо файли за розширенням та статусом
            filtered_files = []
            for file_info in files:
                file_name = file_info.get('name', '')
                file_status = file_info.get('status', '')
                
                # Фільтр по розширенню
                if not any(file_name.lower().endswith(ext.lower()) for ext in file_extensions):
                    continue
                
                # Фільтр по статусу (якщо вказано)
                if status_filter and file_status != status_filter:
                    continue
                
                filtered_files.append(file_info)
            
            logger.info(f"Found {len(filtered_files)} files to download")
            
            # Завантажуємо всі SHA256 хеші з БД для перевірки дублікатів
            existing_hashes = set()
            if skip_duplicates and self.brief_database:
                try:
                    existing_hashes = await self.brief_database.get_all_sha256_hashes()
                    logger.info(f"Loaded {len(existing_hashes)} existing SHA256 hashes from database")
                except Exception as e:
                    logger.warning(f"Failed to load existing hashes: {e}")
            
            # Функція для завантаження одного файлу
            async def download_single_file(file_info: Dict) -> Optional[Dict]:
                """Завантажує один файл з перевіркою дублікатів"""
                file_id = file_info.get('id')
                file_name = file_info.get('name', 'unknown')
                
                if not file_id:
                    logger.warning(f"Skipping file without ID: {file_name}")
                    return None
                
                try:
                    # Створюємо унікальне ім'я файлу
                    timestamp = datetime.now(LOCAL_TZ).strftime("%Y%m%dT%H%M%SZ")
                    local_filename = f"{timestamp}__{file_name}"
                    local_path = Path(self.save_dir) / local_filename
                    
                    # Завантажуємо файл
                    logger.info(f"Downloading {file_name}...")
                    success = await self.google_drive.download_file(
                        file_id,
                        local_path,
                        file_name,
                        use_api=use_api
                    )
                    
                    if not success or not local_path.exists():
                        logger.warning(f"Failed to download: {file_name}")
                        return None
                    
                    # Обчислюємо SHA256
                    with open(local_path, 'rb') as f:
                        file_hash = sha256_bytes(f.read())
                    
                    # Перевіряємо дублікати
                    if skip_duplicates and file_hash in existing_hashes:
                        logger.info(f"Skipping duplicate file: {file_name} (SHA256: {file_hash[:12]}...)")
                        try:
                            local_path.unlink()  # Видаляємо завантажений файл
                        except Exception as e:
                            logger.warning(f"Failed to delete duplicate file {local_path}: {e}")
                        return None
                    
                    # Додаємо хеш до множини для наступних перевірок
                    existing_hashes.add(file_hash)
                    
                    file_size = local_path.stat().st_size / 1024.0  # KB
                    
                    result = {
                        'filename': file_name,
                        'local_path': str(local_path),
                        'sha256': file_hash,
                        'size_kb': file_size,
                        'downloaded_at': datetime.now(LOCAL_TZ).isoformat(),
                        'google_drive_id': file_id,
                        'status': file_info.get('status', 'UNKNOWN')
                    }
                    
                    logger.info(f"Downloaded: {file_name} ({file_size:.2f} KB, SHA256: {file_hash[:12]}...)")
                    return result
                        
                except Exception as e:
                    logger.error(f"Error downloading {file_name}: {e}", exc_info=True)
                    return None
            
            # Завантажуємо файли асинхронно паралельно
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def download_with_semaphore(file_info: Dict):
                """Завантажує файл з обмеженням кількості одночасних завантажень"""
                async with semaphore:
                    return await download_single_file(file_info)
            
            # Створюємо завдання для всіх файлів
            tasks = [download_with_semaphore(file_info) for file_info in filtered_files]
            
            # Виконуємо завантаження паралельно
            logger.info(f"Starting parallel download of {len(tasks)} files (max {max_concurrent} concurrent)...")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Збираємо успішні результати
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Download task failed: {result}", exc_info=True)
                elif result is not None:
                    downloaded_files.append(result)
            
            logger.info(f"Downloaded {len(downloaded_files)} new files from Google Drive (skipped {len(filtered_files) - len(downloaded_files)} duplicates)")
            
        except Exception as e:
            logger.error(f"Error downloading files from Google Drive: {e}", exc_info=True)
        
        return downloaded_files



