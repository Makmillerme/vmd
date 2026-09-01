#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Інтеграція з Google Drive через Google Apps Script API
"""

import asyncio
import base64
import logging
from pathlib import Path
from typing import List, Optional, Dict

import aiohttp
from ..config import (
    GOOGLE_DRIVE_ENABLED, GOOGLE_DRIVE_WEB_APP_URL, GOOGLE_DRIVE_API_KEY
)

logger = logging.getLogger(__name__)


class GoogleDriveIntegration:
    """
    Клас для інтеграції з Google Drive через Google Apps Script Web App
    
    Використовує два способи отримання файлів:
    1. Прямий лінк (швидкий, без API)
    2. API через Apps Script (з логуванням та оновленням статусу)
    """
    
    def __init__(
        self,
        web_app_url: str = None,
        api_key: str = None
    ):
        """
        Ініціалізація інтеграції з Google Drive
        
        Args:
            web_app_url: URL Google Apps Script Web App
            api_key: Секретний ключ для доступу до API
        """
        self.web_app_url = web_app_url or GOOGLE_DRIVE_WEB_APP_URL
        self.api_key = api_key or GOOGLE_DRIVE_API_KEY
        
        if not self.web_app_url:
            raise ValueError("GOOGLE_DRIVE_WEB_APP_URL is required. Set it in .env file or pass as parameter.")
        
        if not self.api_key:
            raise ValueError("GOOGLE_DRIVE_API_KEY is required. Set it in .env file or pass as parameter.")
        
        logger.info("Google Drive integration initialized")
    
    def get_direct_download_url(self, file_id: str) -> str:
        """
        Формує пряме посилання для завантаження файлу з Google Drive
        
        Args:
            file_id: ID файлу в Google Drive
        
        Returns:
            URL для прямого завантаження
        """
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    
    async def list_files(self) -> List[Dict]:
        """
        Отримує список файлів з Google Drive через API
        
        Returns:
            Список словників з інформацією про файли:
            [
                {
                    'id': 'file_id',
                    'name': 'filename.imfx',
                    'status': 'PENDING' | 'DOWNLOADED' | 'PROCESSED'
                },
                ...
            ]
        """
        try:
            url = f"{self.web_app_url}?key={self.api_key}&action=list"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Failed to list files: HTTP {response.status} - {error_text}")
                        return []
                    
                    data = await response.json()
                    
                    if data.get('error'):
                        logger.error(f"API error: {data.get('error')}")
                        return []
                    
                    files = data.get('files', [])
                    logger.info(f"Retrieved {len(files)} files from Google Drive")
                    return files
                    
        except Exception as e:
            logger.error(f"Error listing files from Google Drive: {e}", exc_info=True)
            return []
    
    async def get_file(self, file_id: str) -> Optional[Dict]:
        """
        Отримує файл з Google Drive через API (з Base64 контентом)
        
        Args:
            file_id: ID файлу в Google Drive
        
        Returns:
            Dict з метаданими та контентом файлу:
            {
                'id': 'file_id',
                'name': 'filename.imfx',
                'status': 'DOWNLOADED',
                'fileData': 'base64_encoded_content'
            }
            або None якщо помилка
        """
        try:
            url = f"{self.web_app_url}?key={self.api_key}&action=getFile&id={file_id}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Failed to get file {file_id}: HTTP {response.status} - {error_text}")
                        return None
                    
                    data = await response.json()
                    
                    if data.get('error'):
                        logger.error(f"API error for file {file_id}: {data.get('error')}")
                        return None
                    
                    logger.info(f"Retrieved file {data.get('name', file_id)} from Google Drive")
                    return data
                    
        except Exception as e:
            logger.error(f"Error getting file {file_id} from Google Drive: {e}", exc_info=True)
            return None
    
    async def download_file_direct(
        self,
        file_id: str,
        save_path: Path,
        file_name: Optional[str] = None
    ) -> bool:
        """
        Завантажує файл напряму з Google Drive (без API, швидше)
        
        Args:
            file_id: ID файлу в Google Drive
            save_path: Шлях для збереження файлу
            file_name: Ім'я файлу (опціонально, для логування)
        
        Returns:
            True якщо успішно, False інакше
        """
        try:
            url = self.get_direct_download_url(file_id)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status != 200:
                        logger.error(f"Failed to download file {file_id}: HTTP {response.status}")
                        return False
                    
                    # Зберігаємо файл
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                    
                    logger.info(f"Downloaded file {file_name or file_id} to {save_path}")
                    return True
                    
        except Exception as e:
            logger.error(f"Error downloading file {file_id} directly: {e}", exc_info=True)
            return False
    
    async def download_file_via_api(
        self,
        file_id: str,
        save_path: Path,
        file_name: Optional[str] = None
    ) -> bool:
        """
        Завантажує файл через API (з оновленням статусу в БД)
        
        Args:
            file_id: ID файлу в Google Drive
            save_path: Шлях для збереження файлу
            file_name: Ім'я файлу (опціонально, для логування)
        
        Returns:
            True якщо успішно, False інакше
        """
        try:
            file_data = await self.get_file(file_id)
            
            if not file_data:
                return False
            
            # Декодуємо Base64 контент
            file_content_base64 = file_data.get('fileData')
            if not file_content_base64:
                logger.error(f"No fileData in response for file {file_id}")
                return False
            
            try:
                file_content = base64.b64decode(file_content_base64)
            except Exception as e:
                logger.error(f"Failed to decode Base64 content for file {file_id}: {e}")
                return False
            
            # Зберігаємо файл
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(file_content)
            
            logger.info(f"Downloaded file {file_name or file_id} via API to {save_path}")
            logger.info(f"File status updated to DOWNLOADED in Google Sheets")
            return True
                    
        except Exception as e:
            logger.error(f"Error downloading file {file_id} via API: {e}", exc_info=True)
            return False
    
    async def download_file(
        self,
        file_id: str,
        save_path: Path,
        file_name: Optional[str] = None,
        use_api: bool = False
    ) -> bool:
        """
        Завантажує файл з Google Drive
        
        Args:
            file_id: ID файлу в Google Drive
            save_path: Шлях для збереження файлу
            file_name: Ім'я файлу (опціонально, для логування)
            use_api: Якщо True - використовує API (з оновленням статусу), 
                     якщо False - пряме завантаження (швидше)
        
        Returns:
            True якщо успішно, False інакше
        """
        if use_api:
            return await self.download_file_via_api(file_id, save_path, file_name)
        else:
            return await self.download_file_direct(file_id, save_path, file_name)
