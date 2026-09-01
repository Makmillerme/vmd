#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Асинхронний завантажувач ВМД з пошти
"""

import asyncio
import imaplib
import email
import os
import logging
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict

from ..config import (
    ALLOWED_SENDERS, MIN_SIZE_KB, MAX_SIZE_KB, DOWNLOAD_DELAY, LOCAL_TZ
)
from ..utils.helpers import decode_str, sha256_bytes
from ..utils.imap_utils import (
    connect_imap, format_imap_date, build_imap_search_criteria,
    check_vmd_attachment_lightweight
)
from .database import VMDDatabase

logger = logging.getLogger(__name__)


class AsyncVMDDownloader:
    """Асинхронний завантажувач ВМД з пошти"""
    
    def __init__(
        self,
        save_dir: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        sort_by_date: bool = True,
        database: Optional[VMDDatabase] = None,
    ):
        """
        Args:
            save_dir: Папка для збереження файлів
            date_from: Початкова дата фільтрації (включно). Якщо None - без обмеження
            date_to: Кінцева дата фільтрації (включно). Якщо None - без обмеження
            sort_by_date: Сортувати повідомлення по даті (True - від новіших до старіших, False - від старіших до новіших)
        """
        self.save_dir = save_dir
        self.date_from = date_from
        self.date_to = date_to
        self.sort_by_date = sort_by_date
        self.downloaded_hashes = set()  # Для перевірки дублікатів
        self.database = database
        self._db_hashes_loaded = False
        
        # Створюємо папку якщо не існує
        os.makedirs(save_dir, exist_ok=True)
    
    def _sort_messages_by_date(self, imap_conn: imaplib.IMAP4_SSL, msg_nums: List[bytes]) -> List[bytes]:
        """
        Сортує повідомлення по даті відправки.
        Оптимізована версія: використовує UID для сортування (більший UID = новіше повідомлення).
        Це значно швидше ніж використання INTERNALDATE для кожного повідомлення.
        
        Повертає список msg_nums відсортований від новіших до старіших (або навпаки).
        """
        try:
            # UID вже відсортовані по даті (більший UID = новіше повідомлення)
            # Просто сортуємо по числовому значенню UID
            if self.sort_by_date:
                # Від новіших до старіших (більші UID спочатку)
                return sorted(msg_nums, key=lambda x: int(x), reverse=True)
            else:
                # Від старіших до новіших (менші UID спочатку)
                return sorted(msg_nums, key=lambda x: int(x), reverse=False)
            
        except Exception as e:
            logger.warning(f"Error sorting messages by UID: {e}, using original order")
            return msg_nums
    
    def download_single_attachment(self, attachment_info: Dict) -> Optional[Dict]:
        """Синхронне завантаження одного вкладення"""
        try:
            filename = attachment_info["filename"]
            payload = attachment_info["payload"]
            sha = attachment_info["sha256"]
            size_kb = attachment_info["size_kb"]
            mail_from = attachment_info["source"]
            
            # Зберігаємо файл
            safe_fname = filename.replace(os.path.sep, "_")
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            short = sha[:12]
            out_name = f"{timestamp}__{short}__{safe_fname}"
            out_path = os.path.join(self.save_dir, out_name)
            
            # Синхронне збереження
            with open(out_path, "wb") as f:
                f.write(payload)
            
            self.downloaded_hashes.add(sha)

            downloaded_at = datetime.now(LOCAL_TZ).isoformat()
            
            return {
                "filename": out_name,
                "path": out_path,
                "sha256": sha,
                "size_kb": size_kb,
                "source": mail_from,
                "folder_name": attachment_info.get("folder_name"),
                "message_uid": attachment_info.get("message_uid"),
                "subject": attachment_info.get("subject"),
                "message_id": attachment_info.get("message_id"),
                "sent_at": attachment_info.get("sent_at"),
                "downloaded_at": downloaded_at
            }
            
        except Exception as e:
            logger.error(f"Error downloading attachment {attachment_info.get('filename', 'unknown')}: {e}")
            return None
    
    def _find_and_download_one(self, imap_conn: imaplib.IMAP4_SSL, folders_to_search: List[str], state: Dict) -> Optional[Dict]:
        """
        Знаходить один валідний файл і одразу завантажує його.
        Повертає інформацію про завантажений файл або None, якщо не знайдено.
        state: словник з ключами 'folder_idx' та 'msg_idx' (Dict[str, int])
        """
        start_folder_idx = state.get('folder_idx', 0)
        start_msg_idx = state.get('msg_idx', {})
        
        # Продовжуємо пошук з того місця, де зупинилися
        for folder_idx in range(start_folder_idx, len(folders_to_search)):
            folder_name = folders_to_search[folder_idx]
            
            try:
                # Вибір папки
                typ, data = imap_conn.select(folder_name, readonly=True)
                if typ != "OK":
                    continue
                
                # Формуємо search criteria з урахуванням дат
                search_criteria = build_imap_search_criteria(self.date_from, self.date_to)
                logger.info(f"Пошук в папці '{folder_name}' з критеріями: {search_criteria}")
                
                # Отримуємо список повідомлень з фільтрацією по даті
                typ, data = imap_conn.search(None, search_criteria)
                if typ != "OK":
                    logger.warning(f"IMAP search failed in {folder_name}: {typ}")
                    continue
                if not data or not data[0]:
                    logger.info(f"В папці '{folder_name}' не знайдено повідомлень за вказаними критеріями")
                    continue
                
                # Логуємо кількість знайдених повідомлень
                msg_nums = data[0].split()
                if msg_nums:
                    logger.info(f"Знайдено {len(msg_nums)} повідомлень в папці '{folder_name}'")
                else:
                    logger.info(f"В папці '{folder_name}' не знайдено повідомлень")
                    continue
                
                # Сортування по даті, якщо потрібно
                # UID вже відсортовані по даті (більші UID = новіші повідомлення)
                if self.sort_by_date and msg_nums:
                    # Конвертуємо в int для сортування, потім назад в bytes
                    msg_nums_sorted = sorted(msg_nums, key=lambda x: int(x), reverse=True)
                    msg_nums = msg_nums_sorted
                
                start_idx = start_msg_idx.get(folder_name, 0)
                
                # Скануємо повідомлення починаючи з start_idx
                for msg_idx in range(start_idx, len(msg_nums)):
                    msg_num = msg_nums[msg_idx]
                    
                    try:
                        # Використовуємо оптимізовану легку перевірку (з payload для перевірки розміру)
                        attachment_info = check_vmd_attachment_lightweight(imap_conn, msg_num, folder_name, need_payload=True)
                        if not attachment_info:
                            continue
                        
                        # Перевірка дублікатів
                        sha = sha256_bytes(attachment_info["payload"])
                        if sha in self.downloaded_hashes:
                            logger.info(f"Message {msg_num}: Attachment {attachment_info['filename']} (sha256={sha[:12]}) already found, skipping")
                            continue
                        
                        # Знайдено валідний файл - завантажуємо одразу
                        attachment_info["sha256"] = sha
                        downloaded = self.download_single_attachment(attachment_info)
                        if downloaded:
                            # Оновлюємо індекси для наступного пошуку
                            start_msg_idx[folder_name] = msg_idx + 1
                            state['folder_idx'] = folder_idx
                            state['msg_idx'] = start_msg_idx
                            return downloaded
                    
                    except Exception as e:
                        logger.warning(f"Error processing message {msg_num} in {folder_name}: {e}")
                        continue
                
                # Оновлюємо індекс папки (завершили сканування папки)
                start_msg_idx[folder_name] = 0
                state['folder_idx'] = folder_idx + 1
                state['msg_idx'] = start_msg_idx
            
            except Exception as e:
                logger.error(f"Error scanning folder {folder_name}: {e}")
                continue
        
        return None
    
    async def _ensure_db_hashes_loaded(self):
        """Одноразово завантажує відомі SHA256 з бази даних."""
        if self.database and not self._db_hashes_loaded:
            existing = await self.database.fetch_known_hashes()
            if existing:
                self.downloaded_hashes.update(existing)
                logger.info(f"Preloaded {len(existing)} SHA256 хешів з бази даних")
            self._db_hashes_loaded = True

    async def download_vmds_by_uids(self, vmd_uids: List[tuple], total_count: Optional[int] = None) -> List[Dict]:
        """
        Завантажує ВМД за попередньо знайденими UID повідомлень.
        Це оптимізований режим - не виконує пошук, тільки завантажує вказані повідомлення.
        
        Args:
            vmd_uids: Список кортежів (folder_name, msg_num) для завантаження
        
        Returns:
            Список завантажених файлів
        """
        total = total_count or len(vmd_uids)
        skipped_count = 0
        
        await self._ensure_db_hashes_loaded()
        
        # Підключення до IMAP
        loop = asyncio.get_event_loop()
        imap_conn = await loop.run_in_executor(None, connect_imap)
        
        if not imap_conn:
            print("   Помилка: не вдалося підключитися до пошти")
            return []
        
        downloaded_files = []
        
        try:
            # Групуємо UID по папках для ефективності
            uids_by_folder = {}
            for folder_name, msg_num in vmd_uids:
                if folder_name not in uids_by_folder:
                    uids_by_folder[folder_name] = []
                uids_by_folder[folder_name].append(msg_num)
            
            # Завантажуємо файли з кожної папки
            for folder_name, msg_nums in uids_by_folder.items():
                # Вибір папки
                typ, data = imap_conn.select(folder_name, readonly=True)
                if typ != "OK":
                    continue
                
                # Завантажуємо кожне повідомлення
                for msg_num in msg_nums:
                    try:
                        # Затримка між завантаженнями
                        if len(downloaded_files) > 0:
                            await asyncio.sleep(DOWNLOAD_DELAY)
                        
                        # Використовуємо оптимізовану легку перевірку (з payload для перевірки розміру)
                        attachment_info = await loop.run_in_executor(
                            None,
                            check_vmd_attachment_lightweight,
                            imap_conn,
                            msg_num,
                            folder_name,
                            True,
                            True,
                        )
                        if not attachment_info:
                            continue
                        
                        # Перевірка дублікатів
                        sha = sha256_bytes(attachment_info["payload"])
                        current = len(downloaded_files) + skipped_count + 1
                        if sha in self.downloaded_hashes:
                            skipped_count += 1
                            print(f"   [{current}/{total}] Файл вже завантажений, пропущено", end='\r')
                            continue
                        
                        # Завантажуємо файл
                        attachment_info["sha256"] = sha
                        downloaded = await loop.run_in_executor(
                            None, self.download_single_attachment, attachment_info
                        )
                        
                        if downloaded:
                            downloaded_files.append(downloaded)
                            print(f"   [{len(downloaded_files) + skipped_count}/{total}] Завантажено: {downloaded['filename'][:50]}...", end='\r')
                            continue  # Переходимо до наступного повідомлення
                        
                    except Exception as e:
                        logger.error(f"Error processing message {msg_num}: {e}")
                        continue
            
            print()  # Новий рядок після прогресу
            if skipped_count > 0:
                print(f"   Пропущено (вже в БД): {skipped_count} файлів")
            return downloaded_files
            
        finally:
            try:
                def logout():
                    imap_conn.logout()
                await loop.run_in_executor(None, logout)
            except Exception:
                pass
    
    async def download_vmds(self) -> List[Dict]:
        """
        Завантаження ВСІХ ВМД з пошти за вказаний діапазон дат.
        Завантажує всі файли, які відповідають критеріям дати, без обмеження кількості.
        """
        if self.date_from or self.date_to:
            date_range = []
            if self.date_from:
                date_range.append(f"від {self.date_from.strftime('%Y-%m-%d')}")
            if self.date_to:
                date_range.append(f"до {self.date_to.strftime('%Y-%m-%d')}")
            logger.info(f"Завантаження ВМД за діапазон: {' '.join(date_range)}")
        else:
            logger.info("Завантаження всіх доступних ВМД (без фільтрації по даті)")
        
        if self.sort_by_date:
            logger.info("Сортування: від новіших до старіших")
        
        await self._ensure_db_hashes_loaded()

        # Підключення до IMAP (синхронне)
        loop = asyncio.get_event_loop()
        imap_conn = await loop.run_in_executor(None, connect_imap)
        
        if not imap_conn:
            logger.error("Failed to connect to IMAP")
            return []
        
        try:
            folders_to_search = [
                "INBOX",
                "&BB8EQAQ+BEcEOARCBDAEPQRW-",
            ]
            
            downloaded_files = []
            # Стан для відстеження позиції в папках
            state = {
                'folder_idx': 0,
                'msg_idx': {}  # Зберігаємо позицію в кожній папці
            }
            
            logger.info("Пошук та завантаження всіх ВМД файлів за вказаний діапазон дат...")
            
            # Цикл: знайти -> завантажити -> знайти -> завантажити
            # Завантажуємо ВСІ файли, які відповідають критеріям, без обмеження кількості
            while True:
                # Затримка перед пошуком (крім першого файлу)
                if len(downloaded_files) > 0:
                    await asyncio.sleep(DOWNLOAD_DELAY)
                
                # Знаходимо і завантажуємо один файл
                downloaded = await loop.run_in_executor(
                    None, self._find_and_download_one, imap_conn, folders_to_search, state
                )
                
                if downloaded:
                    downloaded_files.append(downloaded)
                    logger.info(f"Знайдено та завантажено [{len(downloaded_files)}]: {downloaded['filename']}")
                else:
                    # Не знайдено більше файлів
                    logger.info(f"Більше ВМД файлів не знайдено. Завантажено {len(downloaded_files)} файлів загалом.")
                    break
            
            logger.info(f"Успішно завантажено {len(downloaded_files)} ВМД файлів")
            return downloaded_files
            
        finally:
            try:
                def logout():
                    imap_conn.logout()
                await loop.run_in_executor(None, logout)
            except Exception as e:
                logger.debug(f"Error in cleanup: {e}")
                pass


