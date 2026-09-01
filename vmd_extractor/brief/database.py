#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль роботи з базою даних для брифів
"""

import json
import aiosqlite
import logging
from typing import Dict, Optional, List
from pathlib import Path
from datetime import datetime

from ..config import LOCAL_TZ, DB_PATH
from ..utils.helpers import sha256_bytes
from ..utils.common import current_time_iso

logger = logging.getLogger(__name__)





class BriefDatabase:
    """Обгортка над aiosqlite для роботи з брифіами"""
    
    def __init__(self, db_path: Path = None):
        if db_path is None:
            db_path = DB_PATH
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    async def save_brief(
        self,
        source_file: str,
        vin: Optional[str] = None,
        pdf_path: Optional[str] = None,
        images: List[str] = None,
        extract_dir: Optional[str] = None,
        sha256: Optional[str] = None
    ) -> Optional[int]:
        """
        Зберігає бриф в БД
        
        Args:
            source_file: Назва джерельного файлу
            vin: VIN код
            pdf_path: Шлях до PDF файлу
            images: Список шляхів до фото
            extract_dir: Шлях до розпакованої директорії
        
        Returns:
            ID збереженого запису або None
        """
        try:
            images_json = json.dumps(images or [])
            now = current_time_iso()
            
            async with aiosqlite.connect(self.db_path) as db:
                # Перевіряємо чи вже існує запис
                cursor = await db.execute(
                    "SELECT id FROM briefs WHERE source_file = ?",
                    (source_file,)
                )
                existing = await cursor.fetchone()
                
                if existing:
                    # Оновлюємо існуючий запис
                    await db.execute(
                        """
                        UPDATE briefs 
                        SET vin = ?, pdf_path = ?, images_json = ?, extract_dir = ?, sha256 = ?, updated_at = ?
                        WHERE source_file = ?
                        """,
                        (vin, pdf_path, images_json, extract_dir, sha256, now, source_file)
                    )
                    await db.commit()
                    return existing[0]
                else:
                    # Створюємо новий запис
                    cursor = await db.execute(
                        """
                        INSERT INTO briefs (source_file, sha256, vin, pdf_path, images_json, extract_dir, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (source_file, sha256, vin, pdf_path, images_json, extract_dir, now, now)
                    )
                    await db.commit()
                    return cursor.lastrowid
                    
        except Exception as e:
            logger.error(f"Error saving brief: {e}", exc_info=True)
            return None
    
    async def get_brief_by_source_file(self, source_file: str) -> Optional[Dict]:
        """Отримує бриф за назвою файлу"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM briefs WHERE source_file = ?",
                    (source_file,)
                )
                row = await cursor.fetchone()
                if row:
                    result = dict(row)
                    # Парсимо JSON
                    if result.get('images_json'):
                        result['images'] = json.loads(result['images_json'])
                    else:
                        result['images'] = []
                    return result
                return None
        except Exception as e:
            logger.error(f"Error getting brief: {e}", exc_info=True)
            return None
    
    async def get_brief_by_vin(self, vin: str) -> Optional[Dict]:
        """Отримує бриф за VIN кодом"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM briefs WHERE vin = ?",
                    (vin,)
                )
                row = await cursor.fetchone()
                if row:
                    result = dict(row)
                    if result.get('images_json'):
                        result['images'] = json.loads(result['images_json'])
                    else:
                        result['images'] = []
                    return result
                return None
        except Exception as e:
            logger.error(f"Error getting brief by VIN: {e}", exc_info=True)
            return None
    
    async def is_brief_processed(self, source_file: str = None, sha256: str = None) -> bool:
        """
        Перевіряє чи бриф вже оброблений
        
        Args:
            source_file: Назва файлу
            sha256: SHA256 хеш файлу
        
        Returns:
            True якщо бриф вже оброблений
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                if sha256:
                    cursor = await db.execute(
                        "SELECT 1 FROM briefs WHERE sha256 = ? LIMIT 1",
                        (sha256,)
                    )
                    if await cursor.fetchone():
                        return True
                
                if source_file:
                    cursor = await db.execute(
                        "SELECT 1 FROM briefs WHERE source_file = ? LIMIT 1",
                        (source_file,)
                    )
                    if await cursor.fetchone():
                        return True
                
                return False
        except Exception as e:
            logger.error(f"Error checking if brief is processed: {e}", exc_info=True)
            return False
    
    async def get_all_sha256_hashes(self) -> set:
        """
        Отримує всі SHA256 хеші з БД для швидкої перевірки дублікатів
        
        Returns:
            Set з усіма SHA256 хешами
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("SELECT sha256 FROM briefs WHERE sha256 IS NOT NULL")
                rows = await cursor.fetchall()
                return {row[0] for row in rows if row[0]}
        except Exception as e:
            logger.error(f"Error getting all SHA256 hashes: {e}", exc_info=True)
            return set()
    
    async def get_all_briefs(self, limit: int = 100) -> List[Dict]:
        """Отримує всі брифі (з обмеженням)"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT * FROM briefs ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    result = dict(row)
                    if result.get('images_json'):
                        result['images'] = json.loads(result['images_json'])
                    else:
                        result['images'] = []
                    results.append(result)
                return results
        except Exception as e:
            logger.error(f"Error getting all briefs: {e}", exc_info=True)
            return []

