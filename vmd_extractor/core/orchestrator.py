#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Головний оркестратор асинхронної обробки ВМД
"""

import asyncio
import logging
import os
import shutil
from typing import List, Dict, Optional, Tuple
from datetime import date, datetime
from pathlib import Path
import aiosqlite

from .downloader import AsyncVMDDownloader
from .processor import AsyncVMDProcessor
from .parser import AsyncVMDParser
# ExcelExporter імпортується lazy для швидкого старту (pandas ~380ms)
from .database import VMDDatabase
from ..config import (
    FILES_DIR, EXTRACT_DATA_DIR, PDF_DIR, TEMP_EXTRACTED_DIR, DB_PATH, LOCAL_TZ,
    TRELLO_ENABLED, TRELLO_API_KEY, TRELLO_API_TOKEN, TRELLO_DB_CARD,
    TRELLO_BOARD_ID, TRELLO_LIST_ID, TRELLO_UNSYNCED_BATCH,
    get_trello_label_for_vehicle_type_async,
    DISALLOWED_TRELLO_TYPES,
)
from ..utils.pdf_handler import attach_pdf_links, build_pdf_filename
from ..utils.trello_sync import sync_card_data_to_db, compare_card_data
from ..utils.common import vehicle_sort_key

logger = logging.getLogger(__name__)


class VMDOrchestrator:
    """Оркестратор для координації всіх процесів обробки ВМД"""
    
    def __init__(
        self,
        files_dir: str = None,
        extract_data_dir: str = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        sort_by_date: bool = True,
        database: Optional[VMDDatabase] = None,
    ):
        """
        Args:
            files_dir: Папка для збереження завантажених файлів (за замовчуванням з config)
            extract_data_dir: Папка для збереження експортованих даних (за замовчуванням з config)
            date_from: Початкова дата фільтрації (включно). Якщо None - без обмеження
            date_to: Кінцева дата фільтрації (включно). Якщо None - без обмеження
            sort_by_date: Сортувати повідомлення по даті (True - від новіших до старіших)
            database: Користувацький екземпляр VMDDatabase (для тестів)
        """
        if files_dir is None:
            files_dir = str(FILES_DIR)
        if extract_data_dir is None:
            extract_data_dir = str(EXTRACT_DATA_DIR)
        
        self.files_dir = files_dir
        self.extract_data_dir = extract_data_dir
        
        # Ініціалізуємо компоненти
        self.date_from = date_from
        self.date_to = date_to
        self.sort_by_date = sort_by_date

        self.database = database or VMDDatabase(DB_PATH)
        self.downloader = AsyncVMDDownloader(
            files_dir,
            date_from=date_from,
            date_to=date_to,
            sort_by_date=sort_by_date,
            database=self.database,
        )
        self.processor = AsyncVMDProcessor()
        self.parser = AsyncVMDParser()
        self._exporter = None  # Lazy init - pandas важкий (~380ms)
        self._extract_data_dir = extract_data_dir
    
    @property
    def exporter(self):
        """Lazy initialization of ExcelExporter (imports pandas ~380ms)"""
        if self._exporter is None:
            from .exporter import ExcelExporter
            self._exporter = ExcelExporter(self._extract_data_dir, database=self.database)
        return self._exporter
    
    async def run_full_pipeline(self, vmd_uids: Optional[List[Tuple[str, bytes]]] = None, skip_trello: bool = False, sync_existing_trello_cards: bool = False) -> Dict:
        """
        Запуск повного пайплайну обробки ВМД
        
        Args:
            vmd_uids: Список (folder_name, msg_num) для завантаження конкретних повідомлень.
                     Якщо None - виконується звичайний пошук за датами.
            skip_trello: Якщо True - пропускає синхронізацію з Trello (зберігає дані лише в БД).
            sync_existing_trello_cards: Якщо True - після синхронізації оновлює дані всіх існуючих карток з Trello.
                                       На ручному режимі зазвичай False (запитується окремо).
        """
        self._sync_existing_trello_cards = sync_existing_trello_cards
        self._skip_trello = skip_trello
        # Мінімальний вивід для GUI режиму
        print("\nЗапуск обробки ВМД...")
        
        await self.database.initialize()

        results = {
            "downloaded": 0,
            "processed": 0,
            "parsed_records": 0,
            "excel_path": None,
            "db_stats": None,
            "errors": []
        }
        
        cleanup_required = False
        downloaded_files: List[Dict] = []
        try:
            # Крок 1: Завантаження з пошти
            print("\nКрок 1: Завантаження файлів...")
            if vmd_uids:
                # Завантаження за конкретними UID (оптимізований режим)
                downloaded_files = await self.downloader.download_vmds_by_uids(vmd_uids, total_count=len(vmd_uids))
            else:
                # Звичайний режим - пошук за датами
                downloaded_files = await self.downloader.download_vmds()
            results["downloaded"] = len(downloaded_files)
            if downloaded_files:
                cleanup_required = True
                print(f"   Завантажено: {len(downloaded_files)} файлів")
            else:
                print("   Нових файлів не знайдено (всі дані вже записані в БД)")
            
            # Збираємо список перевірених email UID для оновлення updated_at
            checked_email_uids = []
            if vmd_uids:
                # Якщо використовували vmd_uids, конвертуємо bytes в str
                checked_email_uids = [
                    (folder_name, msg_num.decode() if isinstance(msg_num, bytes) else str(msg_num))
                    for folder_name, msg_num in vmd_uids
                ]
            elif downloaded_files:
                # Якщо файли завантажені, беремо UID з них
                checked_email_uids = [
                    (f.get("folder_name", ""), f.get("message_uid", ""))
                    for f in downloaded_files
                    if f.get("folder_name") and f.get("message_uid")
                ]
            
            if not downloaded_files:
                await self._handle_no_downloads(checked_email_uids, results)
                return results
            
            # Крок 2: Розпакування та обробка
            print("\nКрок 2: Розпакування та обробка...")
            file_paths = [f["path"] for f in downloaded_files]
            processed_files = await self.processor.process_files(file_paths, show_progress=True)
            results["processed"] = len(processed_files)
            
            if not processed_files:
                await self._finalize_without_data(results, "No files processed.")
                return results
            
            print(f"   Оброблено: {len(processed_files)} файлів")

            downloaded_map = {item["filename"]: item for item in downloaded_files}
            for file_info in processed_files:
                meta = downloaded_map.get(file_info["source_file"])
                if not meta:
                    continue
                file_info["sha256"] = meta.get("sha256")
                file_info["size_kb"] = meta.get("size_kb")
                file_info["folder_name"] = meta.get("folder_name")
                file_info["message_uid"] = meta.get("message_uid")
                file_info["path"] = meta.get("path")
                file_info["downloaded_at"] = meta.get("downloaded_at")
                file_info["window_started_at"] = self._resolve_window_start()
                file_info["window_ended_at"] = self._resolve_window_end()
            
            # Крок 3: Парсинг даних
            print("\nКрок 3: Парсинг даних...")
            parsed_data = await self.parser.parse_documents(processed_files, show_progress=True)
            results["parsed_records"] = len(parsed_data)
            
            if not parsed_data:
                await self._finalize_without_data(results, "No data parsed.")
                return results

            print(f"   Спарсено: {len(parsed_data)} записів")

            # Крок 4: Збереження PDF та додавання посилань (перед записом у БД)
            print("\nКрок 4: Збереження PDF файлів...")
            attach_pdf_links(parsed_data, processed_files, PDF_DIR)
            print("   PDF файли збережено")

            # Крок 5: Збереження в базу даних
            print("\nКрок 5: Збереження в базу даних...")
            try:
                db_stats = await self.database.persist_pipeline_run(
                    emails=downloaded_files,
                    processed_files=processed_files,
                    vehicles=parsed_data,
                    window_start=self._resolve_window_start(),
                    window_end=self._resolve_window_end(),
                )
                results["db_stats"] = db_stats
                print(f"   База даних оновлена: {db_stats.get('files', 0)} файлів, {db_stats.get('vehicles', 0)} записів")
            except Exception as db_error:
                print(f"   Помилка БД: {db_error}")
                results["errors"].append(f"DB error: {db_error}")
                # Генеруємо Excel навіть якщо є помилка в БД (з наявними даними)
                excel_path = self.exporter.export_all_tables()
                results["excel_path"] = excel_path
                if excel_path:
                    await self._upload_excel_to_trello(excel_path)
                return results

            skip_export = not db_stats or db_stats.get("files", 0) == 0

            if skip_export:
                print("   Оновлення історичних посилань на PDF...")

            await self._backfill_pdf_urls_from_disk()
            
            # Крок 6: Експорт в Excel (перед синхронізацією з Trello)
            print("\nКрок 6: Експорт в Excel...")
            excel_path = self.exporter.export_all_tables()
            results["excel_path"] = excel_path
            
            if excel_path:
                print(f"   Excel експортовано: {excel_path}")
            else:
                print("   Увага: Excel файл не експортовано (перевірте повідомлення вище)")
            
            # Крок 7: Синхронізація з Trello (якщо увімкнено та не пропущено)
            if not skip_trello and TRELLO_ENABLED and db_stats:
                new_vehicle_ids = db_stats.get("new_vehicle_ids", [])
                if new_vehicle_ids:
                    print(f"\nКрок 7: Синхронізація з Trello ({len(new_vehicle_ids)} нових транспортних засобів)...")
                    print("   Примітка: в Trello додаються тільки транспортні засоби з наявним типом техніки")
                    print("   (пропускаються: без типу техніки або 'Автомобіль легковий')")
                    await self._sync_vehicles_to_trello(vehicle_ids=new_vehicle_ids)
                await self._sync_unsynced_vehicles_in_current_range(
                    context="Черга несинхронізованих Trello"
                )
                
                # Синхронізуємо дані всіх існуючих карток з Trello (тільки якщо дозволено)
                if getattr(self, "_sync_existing_trello_cards", False):
                    await self._sync_all_existing_cards_from_trello()
                
                # Завантажуємо Excel в Trello якщо налаштовано та не пропущено Trello
                if excel_path:
                    await self._upload_excel_to_trello(excel_path)
            elif skip_trello:
                print("\nКрок 7: Синхронізація з Trello пропущена (збереження лише в БД)")
            
            print("\nОбробка завершена успішно!")
            cleanup_required = cleanup_required or results["downloaded"] > 0
            
        except Exception as e:
            print(f"\nПомилка обробки: {e}")
            logger.error(f"Помилка пайплайну: {e}", exc_info=True)
            results["errors"].append(str(e))
        finally:
            if cleanup_required:
                print("\nОчищення тимчасових файлів...")
                self._cleanup_downloaded_files()
                self._cleanup_temp_extracted()
        
        # Підсумок з датою виконання
        from datetime import datetime
        from ..config import LOCAL_TZ
        finish_time = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{'='*60}")
        print(f"  ПІДСУМОК ВИКОНАННЯ - {finish_time}")
        print(f"{'='*60}")
        print(f"  Завантажено файлів: {results.get('downloaded', 0)}")
        print(f"  Оброблено файлів: {results.get('processed', 0)}")
        print(f"  Спарсено записів: {results.get('parsed_records', 0)}")
        if results.get('excel_path'):
            print(f"  Excel файл: {results['excel_path']}")
        if results.get('errors'):
            print(f"  Помилки: {len(results['errors'])}")
        print(f"{'='*60}\n")
        
        return results

    def _resolve_window_start(self) -> Optional[str]:
        """Перетворює date_from у ISO, щоб зафіксувати стартове вікно."""
        if isinstance(self.date_from, date):
            dt = datetime.combine(self.date_from, datetime.min.time(), LOCAL_TZ)
            return dt.isoformat()
        return None

    def _resolve_window_end(self) -> Optional[str]:
        """Перетворює date_to у ISO, щоб зафіксувати кінцеве вікно."""
        if isinstance(self.date_to, date):
            end_time = datetime.max.time().replace(microsecond=0)
            dt = datetime.combine(self.date_to, end_time, LOCAL_TZ)
            return dt.isoformat()
        return None
    
    def _get_date_range_filters(self) -> Tuple[Optional[str], Optional[str]]:
        """Повертає поточний діапазон дат у форматі ISO (YYYY-MM-DD)."""
        date_from_str = self.date_from.strftime('%Y-%m-%d') if isinstance(self.date_from, date) else None
        date_to_str = self.date_to.strftime('%Y-%m-%d') if isinstance(self.date_to, date) else None
        return date_from_str, date_to_str
    
    async def _sync_unsynced_vehicles_in_current_range(self, context: str = "Синхронізація з Trello"):
        """
        Створює картки Trello для несинхронізованих ТЗ (черга в БД).
        Auto не обмежує датою вікна IMAP — інакше старі ВМД (інша create_at_ccd) не потрапляють у Trello.
        """
        if not TRELLO_ENABLED:
            return

        unsynced_vehicles = await self.database.get_vehicles_for_trello_sync(
            exclude_synced=True,
            limit=TRELLO_UNSYNCED_BATCH,
        )

        if not unsynced_vehicles:
            logger.debug("Не знайдено несинхронізованих транспортних засобів для Trello")
            return

        vehicle_ids = [v["id"] for v in unsynced_vehicles]
        prefix = context or "Синхронізація з Trello"
        print(
            f"\n{prefix} ({len(vehicle_ids)} з черги несинхронізованих, "
            f"ліміт {TRELLO_UNSYNCED_BATCH} за прогін)..."
        )
        print("   Примітка: в Trello додаються тільки vehicles з наявним vehicle_type")
        print("   (пропускаються: без vehicle_type або 'Автомобіль легковий')")
        await self._sync_vehicles_to_trello(vehicle_ids=vehicle_ids)

    async def sync_trello_for_vins(self, vins: List[str]) -> None:
        """Створює картки Trello для конкретних VIN (операційний виклик)."""
        if not TRELLO_ENABLED:
            print("Trello вимкнено (TRELLO_ENABLED=false)")
            return
        normalized = [v.strip().upper() for v in vins if v and v.strip()]
        if not normalized:
            return
        unsynced = await self.database.get_vehicles_for_trello_sync(
            exclude_synced=True,
            vins=normalized,
        )
        if not unsynced:
            print("Немає несинхронізованих ТЗ для вказаних VIN (або VIN не знайдено).")
            return
        await self._sync_vehicles_to_trello(vehicle_ids=[v["id"] for v in unsynced])
    
    def _cleanup_downloaded_files(self):
        """Очищення завантажених файлів"""
        try:
            if os.path.exists(self.files_dir):
                for filename in os.listdir(self.files_dir):
                    file_path = os.path.join(self.files_dir, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                            logger.debug(f"Removed downloaded file: {filename}")
                    except Exception as e:
                        logger.warning(f"Помилка видалення {filename}: {e}")
        except Exception as e:
            logger.error(f"Помилка очищення завантажених файлів: {e}", exc_info=True)
    
    def _cleanup_temp_extracted(self):
        """
        Очищення розпакованих файлів.
        """
        try:
            if os.path.exists(TEMP_EXTRACTED_DIR):
                for dirname in os.listdir(TEMP_EXTRACTED_DIR):
                    dir_path = os.path.join(TEMP_EXTRACTED_DIR, dirname)
                    try:
                        if os.path.isdir(dir_path):
                            shutil.rmtree(dir_path)
                            logger.debug(f"Removed extracted directory: {dirname}")
                    except Exception as e:
                        logger.warning(f"Помилка видалення розпакованої папки {dirname}: {e}")
        except Exception as e:
            logger.error(f"Помилка очищення розпакованих папок: {e}", exc_info=True)

    async def _handle_no_downloads(self, checked_email_uids: List[Tuple[str, str]], results: Dict):
        """Ситуація коли нові файли не завантажені"""
        print("\nНових файлів не знайдено. Оновлення метаданих...")
        if checked_email_uids:
            try:
                updated_count = await self.database.update_checked_emails(checked_email_uids)
                print(f"   Оновлено метаданих для {updated_count} повідомлень")
            except Exception as e:
                print(f"   Помилка оновлення: {e}")

        try:
            db_stats = await self.database.persist_pipeline_run(
                emails=[],
                processed_files=[],
                vehicles=[],
                window_start=self._resolve_window_start(),
                window_end=self._resolve_window_end(),
            )
            results["db_stats"] = db_stats
        except Exception as db_error:
            print(f"   Помилка синхронізації: {db_error}")

        await self._backfill_pdf_urls_from_disk()
        
        # Синхронізація з Trello: перевіряємо чи є несинхронізовані vehicles за поточним діапазоном дат
        if not getattr(self, "_skip_trello", False) and TRELLO_ENABLED:
            await self._sync_unsynced_vehicles_in_current_range()
            # Синхронізація даних існуючих карток тільки якщо дозволено
            if getattr(self, "_sync_existing_trello_cards", False):
                await self._sync_all_existing_cards_from_trello()
        elif getattr(self, "_skip_trello", False):
            print("\nСинхронізація з Trello пропущена (режим лише БД)")

        print("\nЕкспорт в Excel...")
        excel_path = self.exporter.export_all_tables()
        results["excel_path"] = excel_path
        if excel_path:
            print(f"   Excel експортовано: {excel_path}")
            # Завантажуємо Excel в Trello якщо налаштовано
            if not getattr(self, "_skip_trello", False):
                await self._upload_excel_to_trello(excel_path)
        else:
            print("   Увага: Excel файл не експортовано (перевірте повідомлення вище)")

    async def _upload_excel_to_trello(self, excel_path: Optional[str]):
        """Завантажує Excel файл в Trello як вкладення до картки БД та додає коментар"""
        if not TRELLO_ENABLED:
            logger.debug("Інтеграція з Trello вимкнена, пропускаємо завантаження Excel")
            return
        
        if not TRELLO_DB_CARD:
            logger.warning("TRELLO_DB_CARD не налаштовано, пропускаємо завантаження Excel")
            print("   Увага: TRELLO_DB_CARD не налаштовано, Excel не завантажено в Trello")
            return
        
        if not excel_path:
            logger.warning("Шлях до Excel файлу не вказано, пропускаємо завантаження")
            return
        
        try:
            from ..utils.trello_integration import TrelloIntegration
            from datetime import datetime
            
            trello = TrelloIntegration(
                api_key=TRELLO_API_KEY,
                api_token=TRELLO_API_TOKEN,
                board_id="",  # Не потрібно для оновлення вкладення
                list_id="",   # Не потрібно для оновлення вкладення
                enabled=TRELLO_ENABLED,
            )
            
            # Конвертуємо рядок в Path (може бути як абсолютний, так і відносний шлях)
            excel_file = Path(excel_path)
            if not excel_file.is_absolute():
                # Якщо відносний шлях, спробуємо знайти відносно output_dir
                from ..config import EXTRACT_DATA_DIR
                excel_file = EXTRACT_DATA_DIR / excel_file
                # Якщо все ще не знайдено, спробуємо абсолютний шлях
                if not excel_file.exists():
                    excel_file = Path(excel_path).resolve()
            
            if not excel_file.exists():
                logger.warning(f"Excel файл не знайдено: {excel_file} (оригінальний шлях: {excel_path})")
                print(f"   Увага: Excel файл не знайдено: {excel_file}")
                print(f"   Оригінальний шлях: {excel_path}")
                return
            
            print("   Завантаження Excel в Trello...")
            logger.info(f"Завантаження Excel в Trello картку {TRELLO_DB_CARD}: {excel_file}")
            success = await trello.update_excel_attachment(TRELLO_DB_CARD, excel_file)
            
            if success:
                print("   Excel файл оновлено в Trello")
                logger.info(f"Excel файл успішно завантажено в Trello картку {TRELLO_DB_CARD}")
                
                # Додаємо коментар про оновлення БД
                now = datetime.now(LOCAL_TZ)
                date_str = now.strftime("%d.%m.%Y")
                time_str = now.strftime("%H:%M")
                comment_text = f"БД оновлено {date_str} в {time_str}"
                
                comment_success = await trello.add_comment(TRELLO_DB_CARD, comment_text)
                if comment_success:
                    logger.debug(f"Added comment to Trello DB card: {comment_text}")
                else:
                    logger.warning(f"Не вдалося додати коментар до Trello DB картки")
            else:
                print("   Увага: не вдалося завантажити Excel в Trello (перевірте логи)")
                logger.warning(f"Не вдалося завантажити Excel в Trello картку {TRELLO_DB_CARD}")
        except Exception as e:
            error_msg = f"Failed to upload Excel to Trello: {e}"
            logger.error(error_msg, exc_info=True)
            print(f"   Помилка завантаження Excel в Trello: {e}")

    async def _sync_trello_cards_presence(self, trello) -> Dict[str, int]:
        """
        Синхронізує наявність карток в Trello перед створенням нових.
        
        Оптимізовано: спочатку отримує список ВСІХ архівованих карток з дошки
        одним запитом, потім оновлює БД батчем. Це швидше ніж перевіряти кожну
        картку окремо, особливо при частих маніпуляціях з картками.
        
        Returns:
            Dict з статистикою: {'checked': int, 'found': int, 'missing': int, 'restored': int, 'archived': int}
        """
        logger.info("Запуск синхронізації наявності Trello карток...")
        
        # КРОК 1: Отримуємо всі картки з БД (включаючи раніше архівовані для перевірки розархівування)
        all_cards = await self.database.get_all_trello_cards_with_ids(include_archived=True)
        if not all_cards:
            logger.debug("Немає Trello карток в базі даних для перевірки")
            return {'checked': 0, 'found': 0, 'missing': 0, 'restored': 0, 'archived': 0}
        
        # КРОК 2: Отримуємо ВСІХ архівованих карток з Trello ОДНИМ запитом
        print("   Отримання списку архівованих карток з Trello...")
        archived_card_ids = await trello.get_board_archived_card_ids()
        
        stats = {'checked': len(all_cards), 'found': 0, 'missing': 0, 'restored': 0, 'archived': 0}
        cards_to_restore = []
        cards_to_check_individually = []  # Картки які потрібно перевірити окремо
        
        # КРОК 3: Обробляємо картки з БД, порівнюючи зі списком архівованих
        for card_record in all_cards:
            card_id = card_record.get("trello_card_id")
            if not card_id:
                continue
            
            was_archived_in_db = bool(card_record.get("is_archived", 0))
            was_present = bool(card_record.get("is_present", 1))
            last_known_list_id = card_record.get("last_known_list_id")
            
            if card_id in archived_card_ids:
                # Картка архівована в Trello - оновлюємо БД якщо статус змінився
                if not was_archived_in_db:
                    await self.database.update_trello_card_presence(
                        trello_card_id=card_id,
                        is_present=True,
                        is_archived=True,
                    )
                    logger.debug(f"Картка {card_id} архівована в Trello, позначено в БД")
                stats['archived'] += 1
            else:
                # Картка НЕ в архіві - перевіряємо чи вона була архівована раніше (розархівована?)
                if was_archived_in_db:
                    # Була архівована, але тепер ні - потрібно розархівувати в БД
                    await self.database.update_trello_card_presence(
                        trello_card_id=card_id,
                        is_present=True,
                        is_archived=False,
                    )
                    logger.info(f"Картка {card_id} розархівована в Trello, оновлено БД")
                    stats['found'] += 1
                else:
                    # Картка не архівована і не була архівованою - потрібно перевірити існування
                    cards_to_check_individually.append(card_record)
        
        # КРОК 4: Перевіряємо існування тільки неархівованих карток (їх має бути менше)
        if cards_to_check_individually:
            print(f"   Перевірка {len(cards_to_check_individually)} активних карток...")
            
            for card_record in cards_to_check_individually:
                card_id = card_record.get("trello_card_id")
                was_present = bool(card_record.get("is_present", 1))
                last_known_list_id = card_record.get("last_known_list_id")
                
                # Перевіряємо чи картка існує (не включаючи архівовані, бо їх вже обробили)
                card_info = await trello.get_card_info(card_id, include_archived=False)
                
                if card_info:
                    current_list_id = card_info.get("idList")
                    await self.database.update_trello_card_presence(
                        trello_card_id=card_id,
                        is_present=True,
                        current_list_id=current_list_id,
                        is_archived=False,
                    )
                    stats['found'] += 1
                    
                    if not was_present:
                        logger.info(f"Картка {card_id} була відсутня, але тепер знайдена в списку {current_list_id}")
                else:
                    # Картка не існує в Trello (видалена повністю, а не архівована)
                    await self.database.update_trello_card_presence(
                        trello_card_id=card_id,
                        is_present=False,
                    )
                    stats['missing'] += 1
                    
                    if was_present and last_known_list_id:
                        cards_to_restore.append({
                            'card_id': card_id,
                            'vehicle_id': card_record.get("vehicle_id"),
                            'last_known_list_id': last_known_list_id,
                            'card_name': card_record.get("card_name"),
                        })
                        logger.warning(
                            f"Card {card_id} ({card_record.get('card_name', 'N/A')}) was deleted from Trello. "
                            f"Will restore to list {last_known_list_id}"
                        )
        
        # Відновлюємо видалені картки
        if cards_to_restore:
            logger.info(f"Відновлення {len(cards_to_restore)} видалених карток до їх останніх відомих списків...")
            
            for card_data in cards_to_restore:
                card_id = card_data['card_id']
                vehicle_id = card_data['vehicle_id']
                target_list_id = card_data['last_known_list_id']
                
                try:
                    # Отримуємо дані про vehicle для відновлення картки
                    vehicle = await self.database.get_vehicle_by_id(vehicle_id)
                    if not vehicle:
                        logger.warning(f"Транспортний засіб {vehicle_id} не знайдено, не можу відновити картку {card_id}")
                        continue
                    
                    # Використовуємо прямі колонки БД (нова структура)
                    brand = (vehicle.get("brand") or "").strip()
                    model = (vehicle.get("model") or "").strip()
                    vin = (vehicle.get("vin") or "").strip()
                    
                    if not brand or not model or not vin:
                        logger.warning(f"Неповні дані транспортного засобу для картки {card_id}, не можу відновити")
                        continue
                    
                    # Створюємо картку в останньому відомому списку
                    card_name = f"{brand} {model} {vin}"
                    description = (vehicle.get("description") or "").strip()
                    create_at_ccd = vehicle.get("create_at_ccd")
                    if create_at_ccd:
                        if description:
                            description = f"{description}\n\nДата створення ВМД: {create_at_ccd}"
                        else:
                            description = f"Дата створення ВМД: {create_at_ccd}"
                    
                    vehicle_type = (vehicle.get("vehicle_type") or "").strip()
                    label_id = await get_trello_label_for_vehicle_type_async(vehicle_type, self.database) if vehicle_type else None
                    
                    # Створюємо картку безпосередньо в потрібному списку
                    new_card_id = await trello._create_card(
                        name=card_name,
                        description=description,
                        position=None,  # Додаємо зверху
                        id_labels=[label_id] if label_id else None,
                        target_list_id=target_list_id,  # Створюємо безпосередньо в потрібному списку
                    )
                    
                    if new_card_id:
                        # Додаємо PDF файл якщо є
                        if vehicle.get("pdf_url"):
                            pdf_path = PDF_DIR / Path(vehicle["pdf_url"]).name
                            if pdf_path.exists():
                                await trello._add_attachment(new_card_id, pdf_path)
                        
                        # Додаємо коментар про відновлення
                        comment_text = (
                            f"Картку відновлено ({datetime.now(LOCAL_TZ).strftime('%d.%m.%Y %H:%M:%S')}). "
                            f"Попередня картка була видалена з Trello."
                        )
                        await trello._add_comment(new_card_id, comment_text)
                        
                        # Синхронізуємо повні дані з Trello та зберігаємо в БД
                        await self._sync_card_data_to_db(
                            trello,
                            vehicle_id,
                            new_card_id,
                            target_list_id,
                            vehicle_type=vehicle_type,
                        )
                        
                        stats['restored'] += 1
                        logger.info(f"Restored card {card_id} -> {new_card_id} in list {target_list_id}")
                    else:
                        logger.error(f"Не вдалося відновити картку {card_id}")
                        
                except Exception as e:
                    logger.error(f"Помилка відновлення картки {card_id}: {e}", exc_info=True)
        
        logger.info(
            f"Presence sync completed: checked={stats['checked']}, "
            f"found={stats['found']}, missing={stats['missing']}, restored={stats['restored']}"
        )
        
        return stats

    async def _sync_vehicles_to_trello(self, vehicle_ids: Optional[List[int]] = None):
        """
        Синхронізує транспортні засоби з Trello (створює картки).
        
        Цей метод використовується в основному пайплайні та може виконувати
        як створення нових карток, так і оновлення даних існуючих карток
        (зворотня синхронізація з Trello в БД).
        
        Args:
            vehicle_ids: Список ID vehicles для синхронізації. Якщо None - синхронізує всі несинхронізовані.
        """
        if not TRELLO_ENABLED or not TRELLO_API_KEY or not TRELLO_API_TOKEN:
            logger.debug("Trello integration disabled or not configured, skipping sync")
            return
        
        if not TRELLO_BOARD_ID or not TRELLO_LIST_ID:
            logger.warning("TRELLO_BOARD_ID or TRELLO_LIST_ID not configured, skipping sync")
            return
        
        try:
            from ..utils.trello_integration import TrelloIntegration
            from ..utils.trello_sync_service import TrelloSyncService
            
            trello = TrelloIntegration(
                api_key=TRELLO_API_KEY,
                api_token=TRELLO_API_TOKEN,
                board_id=TRELLO_BOARD_ID,
                list_id=TRELLO_LIST_ID,
                enabled=True,
            )
            
            # Прибираємо некоректні записи trello_cards (порожні card_id)
            removed_empty = await self.database.cleanup_empty_trello_records()
            if removed_empty:
                logger.info(f"Removed {removed_empty} trello card placeholders without card_id")
            
            # Отримуємо транспортні засоби для синхронізації
            if vehicle_ids:
                # Синхронізуємо тільки вказані vehicles (з поточного запуску)
                vehicles = await self.database.get_vehicles_by_ids(vehicle_ids)
            else:
                # Синхронізуємо всі несинхронізовані (для ручної синхронізації)
                vehicles = await self.database.get_vehicles_for_trello_sync(exclude_synced=True)
            
            if not vehicles:
                logger.debug("Немає транспортних засобів для синхронізації з Trello")
                print("   Немає vehicles для синхронізації")
                return
            
            print(f"   Знайдено {len(vehicles)} транспортних засобів для синхронізації")
            print("   Фільтрація: пропускаються без марки/моделі/VIN або з типом 'Автомобіль легковий'")
            
            # Сортуємо по даті створення ВМД (від старіших до новіших)
            vehicles = sorted(vehicles, key=vehicle_sort_key)
            
            # Створюємо сервіс синхронізації
            sync_service = TrelloSyncService(trello, self.database)
            
            # Змінні для відстеження прогресу
            created_count = 0
            updated_count = 0
            skipped_count = 0
            error_count = 0
            
            # Функція для відстеження прогресу
            def progress_callback(idx, total, result):
                nonlocal created_count, updated_count, skipped_count, error_count
                if result.action == 'created':
                    created_count += 1
                elif result.action == 'updated':
                    updated_count += 1
                elif result.action == 'skipped':
                    skipped_count += 1
                elif result.action == 'error':
                    error_count += 1
                
                if idx % 5 == 0 or idx == total:
                    print(f"   Обробка: {idx}/{total} (створено: {created_count}, оновлено: {updated_count}, пропущено: {skipped_count}, помилок: {error_count})", end='\r')
            
            # Виконуємо синхронізацію
            report = await sync_service.sync_vehicles(vehicles, progress_callback=progress_callback)
            
            # Виводимо результати
            if report.total > 0:
                print(f"\n   Trello синхронізація: створено {report.created}, оновлено {report.updated}, пропущено {report.skipped}, помилок {report.errors}")
                if report.skipped_vehicles:
                    logger.debug(f"Skipped vehicles: {report.skipped_vehicles}")
                if report.error_vehicles:
                    logger.warning(f"Error vehicles: {report.error_vehicles}")
            
            # Очищаємо зайві картки (заборонені типи та сироти)
            await self._cleanup_trello_cards(trello)
            
        except Exception as e:
            error_msg = f"Failed to sync vehicles to Trello: {e}"
            logger.error(error_msg, exc_info=True)
            print(f"   Помилка синхронізації Trello: {e}")

    async def create_trello_cards_for_vehicle_ids(self, vehicle_ids: List[int]) -> None:
        """
        Спрощене створення Trello-карток тільки для вказаних vehicles.
        
        ВАЖЛИВО:
        - Перевірка наявності виконується ТІЛЬКИ по БД (таблиця trello_cards).
        - Немає глобальної перевірки/відновлення карток у Trello.
        - Для кожної нової картки після створення все одно робимо один повний
          запит до Trello (`get_full_card_data`) щоб коректно заповнити trello_cards.
        """
        if not vehicle_ids:
            return

        if not TRELLO_ENABLED or not TRELLO_API_KEY or not TRELLO_API_TOKEN:
            logger.debug("Trello integration disabled or not configured, skipping simple VIN sync")
            return

        if not TRELLO_BOARD_ID or not TRELLO_LIST_ID:
            logger.warning("TRELLO_BOARD_ID or TRELLO_LIST_ID not configured, skipping simple VIN sync")
            return

        try:
            from ..utils.trello_integration import TrelloIntegration

            trello = TrelloIntegration(
                api_key=TRELLO_API_KEY,
                api_token=TRELLO_API_TOKEN,
                board_id=TRELLO_BOARD_ID,
                list_id=TRELLO_LIST_ID,
                enabled=True,
            )

            # Беремо тільки ті vehicles, які відповідають переданим ID
            vehicles = await self.database.get_vehicles_by_ids(vehicle_ids)
            if not vehicles:
                print("   Немає vehicles для створення карток (simple VIN sync)")
                return

            print(f"   Simple VIN sync: {len(vehicles)} vehicles для створення карток")
            print("   Перевірка існування ТІЛЬКИ по БД (без зворотньої синхронізації з Trello)")


            created_count = 0
            skipped_count = 0
            error_count = 0
            total = len(vehicles)

            for idx, vehicle in enumerate(vehicles, 1):
                # Використовуємо прямі колонки БД (нова структура)
                brand = (vehicle.get("brand") or "").strip()
                model = (vehicle.get("model") or "").strip()
                vin = (vehicle.get("vin") or "").strip()
                vehicle_type = (vehicle.get("vehicle_type") or "").strip()
                
                # Для контейнерів (змінних кузовів) дозволяємо створення навіть без model або vin
                vehicle_type_lower = vehicle_type.lower() if vehicle_type else ""
                is_container = "контейнер" in vehicle_type_lower or "змінний кузов" in vehicle_type_lower
                
                if is_container:
                    # Для контейнерів: мінімальна вимога - має бути хоча б brand або vin
                    if not brand and not vin:
                        logger.warning(f"Пропускаємо контейнер {vehicle['id']}: відсутні марка та VIN")
                        error_count += 1
                        continue
                else:
                    # Для інших типів: всі три поля обов'язкові
                    if not brand or not model or not vin:
                        logger.warning(f"Пропускаємо транспортний засіб {vehicle['id']} (VIN: {vin}): відсутні обов'язкові поля (марка={bool(brand)}, модель={bool(model)}, vin={bool(vin)})")
                        error_count += 1
                        continue

                # Пропускаємо заборонені типи
                if vehicle_type in DISALLOWED_TRELLO_TYPES:
                    logger.debug(f"Skipping vehicle {vehicle['id']} (VIN: {vin}): disallowed type '{vehicle_type}'")
                    skipped_count += 1
                    continue

                # Якщо є vehicle_type, але немає мітки в БД - пропускаємо
                # (створюємо картки тільки для типів, для яких є мітки)
                if vehicle_type:
                    label_id = await get_trello_label_for_vehicle_type_async(vehicle_type, self.database)
                    if not label_id:
                        logger.debug(f"Skipping vehicle {vehicle['id']} (VIN: {vin}): no Trello label for type '{vehicle_type}'")
                        skipped_count += 1
                        continue
                else:
                    label_id = None

                # Лише внутрішня перевірка по БД
                existing_card = await self.database.get_trello_card_by_vehicle_id(vehicle["id"])
                if existing_card:
                    card_id = (existing_card.get("trello_card_id") or "").strip()
                    is_present = existing_card.get("is_present", 1)
                    if card_id and is_present:
                        logger.debug(f"Skipping vehicle {vehicle['id']} (VIN: {vin}): already has Trello card {card_id}")
                        skipped_count += 1
                        continue

                # Готуємо PDF
                pdf_path = None
                if vehicle.get("pdf_url"):
                    pdf_path = PDF_DIR / Path(vehicle["pdf_url"]).name
                    if not pdf_path.exists():
                        pdf_path = None

                # Формуємо опис з датою ВМД (прямі колонки БД)
                description = (vehicle.get("description") or "").strip()
                create_at_ccd = vehicle.get("create_at_ccd")
                if create_at_ccd:
                    if description:
                        description = f"{description}\n\nДата створення ВМД: {create_at_ccd}"
                    else:
                        description = f"Дата створення ВМД: {create_at_ccd}"

                # Створюємо картку (без додаткових перевірок присутності в Trello)
                # Формуємо повний об'єкт vehicle для синхронізації кастомних полів
                vehicle_data = {
                    "brand": brand,
                    "model": model,
                    "vin": vin,
                    "description": description,
                    "create_at_ccd": create_at_ccd,
                    "year_calendar": vehicle.get("year_calendar"),
                    "vehicle_type": vehicle_type,  # Додаємо vehicle_type для правильного формування назви
                }
                
                card_id = await trello.create_vehicle_card(
                    vehicle=vehicle_data,
                    pdf_path=pdf_path,
                    calculate_position=True,
                    label_ids=[label_id] if label_id else None,
                )

                if card_id:
                    # Один повний запит до Trello, щоб коректно записати картку в trello_cards
                    try:
                        await self._sync_card_data_to_db(
                            trello,
                            vehicle["id"],
                            card_id,
                            TRELLO_LIST_ID,
                            vehicle_type=vehicle_type,
                        )
                        created_count += 1
                        logger.info(f"Успішно створено Trello картку {card_id} для транспортного засобу {vehicle['id']} (VIN: {vin})")
                    except Exception as e:
                        logger.error(f"Помилка збереження Trello картки {card_id} в БД для транспортного засобу {vehicle['id']} (VIN: {vin}): {e}", exc_info=True)
                        error_count += 1
                else:
                    logger.error(f"Не вдалося створити Trello картку для транспортного засобу {vehicle['id']} (VIN: {vin}, марка={brand}, модель={model})")
                    error_count += 1

                if idx % 5 == 0 or idx == total:
                    print(
                        f"   Simple VIN sync: {idx}/{total} (створено: {created_count}, "
                        f"пропущено: {skipped_count}, помилок: {error_count})",
                        end="\r",
                    )

            print(
                f"\n   Simple VIN sync завершено: створено {created_count}, "
                f"пропущено (вже є в БД): {skipped_count}, помилок: {error_count}"
            )

        except Exception as e:
            error_msg = f"Failed to run simple VIN Trello sync: {e}"
            logger.error(error_msg, exc_info=True)
            print(f"   Помилка simple VIN Trello sync: {e}")




    async def _sync_card_data_to_db(
        self,
        trello,
        vehicle_id: int,
        card_id: str,
        list_id: str,
        vehicle_type: Optional[str] = None,
    ):
        """
        Синхронізує повні дані картки з Trello в БД з перевіркою змін та retry механізмом.
        Використовує спільну функцію sync_card_data_to_db з utils.trello_sync.
        """
        # Використовуємо спільну функцію з retry механізмом
        success = await sync_card_data_to_db(
            trello=trello,
            database=self.database,
                        vehicle_id=vehicle_id,
            card_id=card_id,
            list_id=list_id,
            vehicle_type=vehicle_type,
            max_retries=3,
        )
        if not success:
            logger.error(f"Не вдалося синхронізувати картку {card_id} з БД після повторних спроб")
            # Зберігаємо базову інформацію навіть якщо синхронізація не вдалася
            try:
                await self.database.save_trello_card(
                    vehicle_id=vehicle_id,
                    trello_card_id=card_id,
                    trello_list_id=list_id,
                    status="error",
                )
            except Exception as e:
                logger.warning(f"Не вдалося зберегти статус помилки для картки {card_id}: {e}")

    async def _sync_all_existing_cards_from_trello(self):
        """
        Синхронізує дані всіх існуючих Trello карток після вивантаження ВМД.
        Оновлює дані тільки якщо вони змінились в Trello.
        
        Оптимізовано: спочатку отримує список ВСІХ архівованих карток з дошки
        одним запитом, потім пропускає їх при синхронізації. Це економить
        API запити при великій кількості архівованих карток.
        """
        if not TRELLO_ENABLED or not TRELLO_API_KEY or not TRELLO_API_TOKEN:
            return
        
        if not TRELLO_BOARD_ID or not TRELLO_LIST_ID:
            return
        
        try:
            from ..utils.trello_integration import TrelloIntegration
            
            trello = TrelloIntegration(
                api_key=TRELLO_API_KEY,
                api_token=TRELLO_API_TOKEN,
                board_id=TRELLO_BOARD_ID,
                list_id=TRELLO_LIST_ID,
                enabled=True,
            )
            
            # КРОК 1: Отримуємо список архівованих карток ОДНИМ запитом
            print("   Отримання списку архівованих карток...")
            archived_card_ids = await trello.get_board_archived_card_ids()
            
            # КРОК 2: Отримуємо всі картки з БД
            rows = await self.database.get_all_trello_cards_with_ids(include_archived=True)
            
            if not rows:
                logger.debug("No Trello cards to sync")
                return
            
            # Фільтруємо архівовані картки та оновлюємо їх статус в БД
            active_rows = []
            archived_count = 0
            
            for row in rows:
                card_id = row.get("trello_card_id")
                if not card_id:
                    continue
                    
                if card_id in archived_card_ids:
                    # Картка архівована - оновлюємо статус в БД якщо потрібно
                    if not row.get("is_archived", 0):
                        await self.database.update_trello_card_presence(
                            trello_card_id=card_id,
                            is_present=True,
                            is_archived=True,
                        )
                    archived_count += 1
                else:
                    active_rows.append(row)
            
            if not active_rows:
                if archived_count > 0:
                    print(f"   Пропущено {archived_count} архівованих карток")
                logger.debug("No active Trello cards to sync")
                return
            
            print(f"\n   Синхронізація даних {len(active_rows)} активних карток з Trello (пропущено {archived_count} архівованих)...")
            synced_count = 0
            error_count = 0
            
            # КРОК 3: Синхронізуємо тільки активні картки
            try:
                for idx, row in enumerate(active_rows, 1):
                    if idx % 5 == 0:
                        await asyncio.sleep(0)  # Щоб Ctrl+C оброблявся без зависання
                    vehicle_id = row["vehicle_id"]
                    card_id = row["trello_card_id"]
                    list_id = row["trello_list_id"] or TRELLO_LIST_ID
                    
                    try:
                        await self._sync_card_data_to_db(trello, vehicle_id, card_id, list_id)
                        synced_count += 1
                        
                        if idx % 10 == 0 or idx == len(active_rows):
                            print(f"   Обробка: {idx}/{len(active_rows)} (оновлено: {synced_count}, помилок: {error_count})", end='\r')
                    except (KeyboardInterrupt, asyncio.CancelledError):
                        raise
                    except Exception as e:
                        logger.error(f"Error syncing card {card_id}: {e}")
                        error_count += 1
                
                if synced_count > 0 or archived_count > 0 or error_count > 0:
                    print(f"\n   Синхронізовано {synced_count} карток, архівованих: {archived_count}, помилок: {error_count}")
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\n   Синхронізацію карток перервано користувачем.")
                raise
        except (KeyboardInterrupt, asyncio.CancelledError):
            raise
        except Exception as e:
            logger.error(f"Error syncing all existing cards: {e}", exc_info=True)
    
    async def _cleanup_trello_cards(self, trello):
        """Видаляє з Trello заборонені або осиротілі картки та оновлює БД"""
        if not TRELLO_ENABLED or trello is None:
            return 0
        

        
        try:
            disallowed_cards = await self.database.get_trello_cards_by_vehicle_types(list(DISALLOWED_TRELLO_TYPES))
            orphan_cards = await self.database.get_orphan_trello_cards()
            
            targets = disallowed_cards + orphan_cards
            if not targets:
                return 0
            
            removed = 0
            processed_ids = set()
            for card in targets:
                card_id = card.get("trello_card_id")
                vehicle_id = card.get("vehicle_id")
                
                if card_id in processed_ids:
                    continue
                if card_id:
                    success = await trello.delete_card(card_id)
                else:
                    success = True  # Немає card_id, але потрібно прибрати запис
                
                if success:
                    await self.database.delete_trello_card_record(vehicle_id=vehicle_id, trello_card_id=card_id)
                    removed += 1
                    processed_ids.add(card_id)
            
            if removed > 0:
                logger.info(f"Cleaned up {removed} Trello cards (disallowed types and orphans)")
            
            return removed
        except Exception as e:
            logger.error(f"Error cleaning up Trello cards: {e}", exc_info=True)
            return 0

    async def _backfill_pdf_urls_from_disk(self) -> int:
        """
        Відновлює pdf_url у БД, якщо відповідні PDF вже існують на диску.
        Використовується для старих записів, створених до фіксації.
        """
        missing = await self.database.fetch_vehicles_missing_pdf()
        if not missing:
            return 0

        pdf_dir = Path(PDF_DIR)
        pdf_dir.mkdir(parents=True, exist_ok=True)

        updates: List[Tuple[int, str]] = []
        for item in missing:
            payload = item.get("payload") or {}
            fallback_name = item.get("filename") or payload.get("mrn") or "document"

            pdf_filename = build_pdf_filename(payload, fallback_name)
            target_path = pdf_dir / pdf_filename

            if not target_path.exists():
                candidate = next(
                    (p for p in pdf_dir.glob(f"{target_path.stem}*.pdf") if p.is_file()),
                    None,
                )
                if not candidate:
                    continue
                target_path = candidate

            relative_path = Path("pdf") / target_path.name
            updates.append((item["vehicle_id"], relative_path.as_posix()))

        updated = await self.database.bulk_update_pdf_urls(updates)
        if updated:
            logger.info(f"Backfilled pdf_url for {updated} vehicles using existing PDF files.")
        return updated

    async def _finalize_without_data(self, results: Dict, message: str):
        """Завершення пайплайну без нових даних (але з синхронізацією БД та Excel)."""
        print(f"\n{message} Оновлення метаданих та Excel...")
        try:
            db_stats = await self.database.persist_pipeline_run(
                emails=[],
                processed_files=[],
                vehicles=[],
                window_start=self._resolve_window_start(),
                window_end=self._resolve_window_end(),
            )
            results["db_stats"] = db_stats
        except Exception as db_error:
            print(f"   Помилка синхронізації: {db_error}")

        await self._backfill_pdf_urls_from_disk()
        
        # Експорт в Excel (перед синхронізацією з Trello)
        print("\nЕкспорт в Excel...")
        excel_path = self.exporter.export_all_tables()
        results["excel_path"] = excel_path
        if excel_path:
            print(f"   Excel експортовано: {excel_path}")
        else:
            print("   Увага: Excel файл не експортовано (перевірте повідомлення вище)")
        
        # Синхронізація з Trello (якщо увімкнено)
        if TRELLO_ENABLED:
            print("\nСинхронізація з Trello...")
            await self._sync_vehicles_to_trello()
            # Завантажуємо Excel в Trello якщо налаштовано
            if excel_path:
                await self._upload_excel_to_trello(excel_path)


