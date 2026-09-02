#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль роботи з базою даних (SQLite + aiosqlite) для VMD Extractor.
Відповідає за:
 - ініціалізацію схеми (email_messages, processed_files, vehicles, sync_runs)
 - керування транзакціями
 - запис метаданих завантажених файлів та результатів парсингу
 - швидкі перевірки дублікатів за SHA256
 - збереження контрольних точок (останнє успішне вивантаження)
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import aiosqlite
import logging

from ..config import LOCAL_TZ, PDF_DIR  # Trello imports removed (unused)
from ..utils.common import current_time_iso

logger = logging.getLogger(__name__)




@dataclass
class EmailMetadata:
    folder_name: str
    message_uid: str
    sender: str
    subject: Optional[str]
    message_id: Optional[str]
    sent_at: Optional[str]


@dataclass
class ProcessedFileRecord:
    filename: str
    sha256: str
    size_kb: float
    stored_path: str
    downloaded_at: str
    folder_name: str
    message_uid: str
    window_started_at: Optional[str]
    window_ended_at: Optional[str]


class VMDDatabase:
    """Обгортка над aiosqlite з утворенням схеми та корисними методами."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """Створення таблиць та необхідних індексів (ідемпотентно)."""
        async with self._init_lock:
            if self._initialized:
                return

            # Спочатку виконуємо міграції для існуючих таблиць (перед створенням нових)
            # Гарантуємо наявність колонки sha256 у briefs (для перевірки дублікатів)
            try:
                async with aiosqlite.connect(self.db_path) as db:
                    # Перевіряємо чи існує таблиця briefs
                    cursor = await db.execute("""
                        SELECT name FROM sqlite_master 
                        WHERE type='table' AND name='briefs'
                    """)
                    if await cursor.fetchone():
                        # Таблиця існує - перевіряємо чи є колонка sha256
                        cursor = await db.execute("PRAGMA table_info(briefs)")
                        columns = {row[1] for row in await cursor.fetchall()}
                        if "sha256" not in columns:
                            await db.execute("ALTER TABLE briefs ADD COLUMN sha256 TEXT")
                            await db.commit()
                            logger.info("Added sha256 column to briefs table")
                        
                        # Створюємо індекс на sha256 якщо його немає
                        cursor = await db.execute("""
                            SELECT name FROM sqlite_master 
                            WHERE type='index' AND name='idx_briefs_sha256'
                        """)
                        if not await cursor.fetchone():
                            try:
                                await db.execute("CREATE INDEX idx_briefs_sha256 ON briefs(sha256)")
                                await db.commit()
                                logger.info("Created index idx_briefs_sha256 on briefs table")
                            except Exception as e:
                                logger.warning(f"Could not create index idx_briefs_sha256: {e}")
            except Exception as e:
                logger.warning(f"Error during briefs migration: {e}")

            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA journal_mode=WAL;")
                await db.execute("PRAGMA foreign_keys=ON;")
                await db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS email_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        folder_name TEXT NOT NULL,
                        message_uid TEXT NOT NULL,
                        sender TEXT,
                        subject TEXT,
                        message_id TEXT,
                        sent_at TEXT,
                        has_vmd INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(folder_name, message_uid)
                    );

                    CREATE TABLE IF NOT EXISTS processed_files (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email_message_id INTEGER,
                        filename TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        size_kb REAL,
                        stored_path TEXT,
                        downloaded_at TEXT NOT NULL,
                        window_started_at TEXT,
                        window_ended_at TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(email_message_id) REFERENCES email_messages(id) ON DELETE SET NULL,
                        UNIQUE(sha256)
                    );

                    CREATE TABLE IF NOT EXISTS vehicles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        processed_file_id INTEGER NOT NULL,
                        mrn TEXT,
                        vin TEXT,
                        model TEXT,
                        customs_value TEXT,
                        create_at_ccd TEXT,
                        pdf_url TEXT,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(processed_file_id) REFERENCES processed_files(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS sync_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        window_start TEXT,
                        window_end TEXT,
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        files_downloaded INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS trello_cards (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vehicle_id INTEGER NOT NULL UNIQUE,
                        trello_card_id TEXT UNIQUE,
                        trello_list_id TEXT NOT NULL,
                        trello_list_name TEXT,
                        card_name TEXT,
                        description TEXT,
                        card_pos REAL,
                        synced_at TEXT NOT NULL,
                        last_sync_status TEXT NOT NULL DEFAULT 'success',
                        attachments_json TEXT,
                        media_files_json TEXT,
                        checklists_json TEXT,
                        comments_json TEXT,
                        labels_json TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
                    );

                    CREATE INDEX IF NOT EXISTS idx_email_messages_folder_uid
                        ON email_messages(folder_name, message_uid);
                    CREATE INDEX IF NOT EXISTS idx_processed_files_sha
                        ON processed_files(sha256);
                    CREATE INDEX IF NOT EXISTS idx_processed_files_downloaded
                        ON processed_files(downloaded_at);
                    CREATE INDEX IF NOT EXISTS idx_vehicles_mrn
                        ON vehicles(mrn);
                    -- Додаємо UNIQUE constraint на vehicle_id якщо його немає (для існуючих БД)
                    -- Перевіряємо чи constraint вже існує
                    CREATE INDEX IF NOT EXISTS idx_trello_cards_vehicle_id
                        ON trello_cards(vehicle_id);
                    
                    CREATE INDEX IF NOT EXISTS idx_vehicles_vin
                        ON vehicles(vin);
                    CREATE INDEX IF NOT EXISTS idx_sync_runs_status
                        ON sync_runs(status);
                    CREATE INDEX IF NOT EXISTS idx_trello_cards_vehicle_id
                        ON trello_cards(vehicle_id);
                    CREATE INDEX IF NOT EXISTS idx_trello_cards_card_id
                        ON trello_cards(trello_card_id);
                    CREATE INDEX IF NOT EXISTS idx_trello_cards_list_id
                        ON trello_cards(trello_list_id);

                    CREATE TABLE IF NOT EXISTS trello_labels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        vehicle_type TEXT NOT NULL UNIQUE,
                        trello_label_id TEXT NOT NULL,
                        label_name TEXT,
                        label_color TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_trello_labels_vehicle_type
                        ON trello_labels(vehicle_type);
                    CREATE INDEX IF NOT EXISTS idx_trello_labels_label_id
                        ON trello_labels(trello_label_id);

                    CREATE TABLE IF NOT EXISTS briefs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_file TEXT NOT NULL,
                        vin TEXT,
                        pdf_path TEXT,
                        images_json TEXT,
                        extract_dir TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(source_file)
                    );

                    CREATE INDEX IF NOT EXISTS idx_briefs_vin
                        ON briefs(vin);
                    CREATE INDEX IF NOT EXISTS idx_briefs_source_file
                        ON briefs(source_file);
                    """
                )
                await db.commit()
            
            # Міграція: додаємо нові колонки до існуючої таблиці trello_cards (якщо їх немає)
            async with aiosqlite.connect(self.db_path) as db:
                await self._migrate_trello_cards_table(db)
            
            # Міграція: створюємо таблицю trello_labels якщо її немає (для старих БД)
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name='trello_labels'
                """)
                if not await cursor.fetchone():
                    await db.executescript("""
                        CREATE TABLE trello_labels (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            vehicle_type TEXT NOT NULL UNIQUE,
                            trello_label_id TEXT NOT NULL,
                            label_name TEXT,
                            label_color TEXT,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        );
                        CREATE INDEX idx_trello_labels_vehicle_type
                            ON trello_labels(vehicle_type);
                        CREATE INDEX idx_trello_labels_label_id
                            ON trello_labels(trello_label_id);
                    """)
                    await db.commit()

            # Гарантуємо наявність колонки pdf_url у vehicles (для старих БД)
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("PRAGMA table_info(vehicles)")
                columns = {row[1] for row in await cursor.fetchall()}
                if "pdf_url" not in columns:
                    await db.execute("ALTER TABLE vehicles ADD COLUMN pdf_url TEXT")
                    await db.commit()
            
            # Гарантуємо наявність колонки brief_pdf_path у vehicles (для співставлення з брифіами)
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute("PRAGMA table_info(vehicles)")
                columns = {row[1] for row in await cursor.fetchall()}
                if "brief_pdf_path" not in columns:
                    await db.execute("ALTER TABLE vehicles ADD COLUMN brief_pdf_path TEXT")
                    await db.commit()
                    logger.info("Added brief_pdf_path column to vehicles table")

            # Додаємо UNIQUE constraint на vehicle_id для існуючих БД (якщо його немає)
            async with aiosqlite.connect(self.db_path) as db:
                # Перевіряємо чи constraint вже існує
                cursor = await db.execute("""
                    SELECT sql FROM sqlite_master 
                    WHERE type='table' AND name='trello_cards'
                """)
                table_sql = await cursor.fetchone()
                if table_sql and table_sql[0]:
                    # Перевіряємо чи є UNIQUE constraint на vehicle_id
                    if 'vehicle_id INTEGER NOT NULL UNIQUE' not in table_sql[0] and 'vehicle_id INTEGER NOT NULL,' in table_sql[0]:
                        try:
                            # Створюємо нову таблицю з UNIQUE constraint
                            await db.execute("""
                                CREATE TABLE trello_cards_new (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    vehicle_id INTEGER NOT NULL UNIQUE,
                                    trello_card_id TEXT UNIQUE,
                                    trello_list_id TEXT NOT NULL,
                                    trello_list_name TEXT,
                                    card_name TEXT,
                                    description TEXT,
                                    card_pos REAL,
                                    synced_at TEXT NOT NULL,
                                    last_sync_status TEXT NOT NULL DEFAULT 'success',
                                    attachments_json TEXT,
                                    media_files_json TEXT,
                                    checklists_json TEXT,
                                    comments_json TEXT,
                                    labels_json TEXT,
                                    is_present INTEGER DEFAULT 1,
                                    last_known_list_id TEXT,
                                    created_at TEXT NOT NULL,
                                    updated_at TEXT NOT NULL,
                                    FOREIGN KEY(vehicle_id) REFERENCES vehicles(id) ON DELETE CASCADE
                                )
                            """)
                            # Копіюємо дані (видаляємо дублікати, залишаємо тільки останній запис для кожного vehicle_id)
                            await db.execute("""
                                INSERT INTO trello_cards_new 
                                SELECT * FROM trello_cards
                                WHERE id IN (
                                    SELECT MAX(id) FROM trello_cards GROUP BY vehicle_id
                                )
                            """)
                            # Видаляємо стару таблицю
                            await db.execute("DROP TABLE trello_cards")
                            # Перейменовуємо нову таблицю
                            await db.execute("ALTER TABLE trello_cards_new RENAME TO trello_cards")
                            # Відновлюємо індекси
                            await db.execute("""
                                CREATE INDEX IF NOT EXISTS idx_trello_cards_vehicle_id
                                    ON trello_cards(vehicle_id);
                            """)
                            await db.execute("""
                                CREATE INDEX IF NOT EXISTS idx_trello_cards_card_id
                                    ON trello_cards(trello_card_id);
                            """)
                            await db.execute("""
                                CREATE INDEX IF NOT EXISTS idx_trello_cards_list_id
                                    ON trello_cards(trello_list_id);
                            """)
                            await db.commit()
                            logger.info("Added UNIQUE constraint on vehicle_id in trello_cards table")
                        except Exception as e:
                            logger.warning(f"Could not add UNIQUE constraint on vehicle_id: {e}")
                            await db.rollback()

            self._initialized = True

    async def fetch_known_hashes(self) -> List[str]:
        """Повертає список усіх збережених SHA256 (для швидкої перевірки дублікатів)."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT sha256 FROM processed_files")
            rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def is_hash_known(self, sha256: str) -> bool:
        """Перевірка, чи існує файл із заданим SHA256."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT 1 FROM processed_files WHERE sha256 = ? LIMIT 1",
                (sha256,),
            )
            return await cursor.fetchone() is not None

    async def _upsert_email(
        self, db: aiosqlite.Connection, meta: EmailMetadata
    ) -> int:
        """Створює або оновлює запис email та повертає його ID."""
        now_iso = current_time_iso()
        await db.execute(
            """
            INSERT INTO email_messages (folder_name, message_uid, sender, subject, message_id, sent_at, has_vmd, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(folder_name, message_uid)
            DO UPDATE SET
                sender = excluded.sender,
                subject = excluded.subject,
                message_id = excluded.message_id,
                sent_at = excluded.sent_at,
                has_vmd = 1,
                updated_at = ?
            """,
            (
                meta.folder_name,
                meta.message_uid,
                meta.sender,
                meta.subject,
                meta.message_id,
                meta.sent_at,
                now_iso,
                now_iso,
                now_iso,  # для UPDATE
            ),
        )
        cursor = await db.execute(
            "SELECT id FROM email_messages WHERE folder_name = ? AND message_uid = ?",
            (meta.folder_name, meta.message_uid),
        )
        row = await cursor.fetchone()
        return int(row[0])

    async def persist_pipeline_run(
        self,
        *,
        emails: Sequence[Dict],
        processed_files: Sequence[Dict],
        vehicles: Sequence[Dict],
        window_start: Optional[str],
        window_end: Optional[str],
    ) -> Dict[str, int]:
        """
        Зберігає результати пайплайну в одній транзакції.
        emails            — сирий список dict з downloader (folder, uid, sender, subject, message_id, sent_at).
        processed_files   — dict з processor (файл, sha, розмір, шлях, downloaded_at).
        vehicles          — результат парсингу (кожен dict містить source_file).
        """
        # Навіть якщо немає нових файлів, оновлюємо updated_at для перевірених email
        update_emails_only = not processed_files

        await self.initialize()
        started_at = current_time_iso()
        inserted_files = 0
        inserted_vehicles = 0
        new_vehicle_ids = []  # Зберігаємо ID нових vehicles для синхронізації з Trello

        email_cache: Dict[Tuple[str, str], int] = {}
        file_id_by_name: Dict[str, int] = {}

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.execute("BEGIN")
            try:
                # Крок 1. Email метадані (завжди обробляємо, навіть якщо немає нових файлів)
                for email_info in emails:
                    key = (
                        email_info.get("folder_name", ""),
                        email_info.get("message_uid", ""),
                    )
                    if not key[0] or not key[1]:
                        continue
                    if key in email_cache:
                        continue
                    meta = EmailMetadata(
                        folder_name=key[0],
                        message_uid=key[1],
                        sender=email_info.get("source", ""),
                        subject=email_info.get("subject"),
                        message_id=email_info.get("message_id"),
                        sent_at=email_info.get("sent_at"),
                    )
                    email_cache[key] = await self._upsert_email(db, meta)

                # Якщо немає нових файлів, тільки оновлюємо email і створюємо sync_runs запис
                if update_emails_only:
                    await db.execute(
                        """
                        INSERT INTO sync_runs (
                            window_start, window_end, started_at, finished_at,
                            files_downloaded, status, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            window_start,
                            window_end,
                            started_at,
                            current_time_iso(),
                            0,  # files_downloaded = 0
                            "success",
                            current_time_iso(),
                        ),
                    )
                    await db.commit()
                    return {
                        "emails": len(email_cache),
                        "files": 0,
                        "vehicles": 0,
                    }

                # Крок 2. processed_files
                for file_info in processed_files:
                    filename = file_info.get("source_file")
                    sha256 = file_info.get("sha256")
                    if not filename or not sha256:
                        continue

                    folder = file_info.get("folder_name", "")
                    msg_uid = file_info.get("message_uid", "")
                    email_id = email_cache.get((folder, msg_uid))

                    insert_cursor = await db.execute(
                        """
                        INSERT INTO processed_files (
                            email_message_id, filename, sha256, size_kb,
                            stored_path, downloaded_at, window_started_at, window_ended_at, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(sha256) DO NOTHING
                        """,
                        (
                            email_id,
                            filename,
                            sha256,
                            file_info.get("size_kb"),
                            file_info.get("path"),
                            file_info.get("downloaded_at"),
                            file_info.get("window_started_at", window_start),
                            file_info.get("window_ended_at", window_end),
                            current_time_iso(),
                        ),
                    )

                    # Перевіряємо чи файл був вставлений (новий файл)
                    was_inserted = insert_cursor.rowcount > 0
                    if was_inserted:
                        inserted_files += 1

                    # Отримуємо ID файлу (якщо вставлено новий або вже існує)
                    cursor = await db.execute(
                        "SELECT id FROM processed_files WHERE sha256 = ?",
                        (sha256,),
                    )
                    row = await cursor.fetchone()
                    if row:
                        file_id_by_name[filename] = int(row[0])

                # Крок 3. vehicles
                for vehicle in vehicles:
                    source_file = vehicle.get("source_file")
                    if not source_file:
                        continue
                    processed_id = file_id_by_name.get(source_file)
                    if not processed_id:
                        continue

                    # Видаляємо всі технічні поля про файл з payload
                    # Технічні дані про файл мають бути тільки в processed_files
                    vehicle_payload = dict(vehicle)
                    technical_fields = [
                        "source_file",  # Назва файлу
                        "filename",     # Технічні дані про файл
                        "path",         # Шлях до файлу
                        "sha256",       # Хеш файлу
                        "size_kb",      # Розмір файлу
                        "downloaded_at", # Час завантаження
                        "window_started_at",  # Вікно початку
                        "window_ended_at",     # Вікно кінця
                        "created_at",   # Час створення запису
                        "email_message_id",    # ID email повідомлення
                        "processed_file_id",   # ID обробленого файлу
                    ]
                    for field in technical_fields:
                        vehicle_payload.pop(field, None)

                    unwanted_fields = [
                        "invoice_name",
                        "vat_percent",
                        "vat_amount_uah",
                        "trademark",
                        "producer",
                        "origin_country",
                    ]
                    for field in unwanted_fields:
                        vehicle_payload.pop(field, None)

                    payload_json = json.dumps(vehicle_payload, ensure_ascii=False)
                    
                    # Нормалізовані колонки
                    vehicle_type = (vehicle.get("vehicle_type") or "").strip() or None
                    brand = (vehicle.get("brand") or "").strip() or None
                    uktzed = (vehicle.get("uktzed") or "").strip() or None
                    description = (vehicle.get("description") or "").strip() or None
                    producer_country = (vehicle.get("producer_country") or "").strip() or None
                    gross_weight = str(vehicle.get("gross_weight") or "").strip() or None
                    net_weight = str(vehicle.get("net_weight") or "").strip() or None
                    wheel_formula = (vehicle.get("wheel_formula") or "").strip() or None
                    serial_number = (vehicle.get("serial_number") or "").strip() or None
                    unit_human = (vehicle.get("unit_human") or "").strip() or None
                    
                    # Для контейнерів та спецтехніки: serial_number = VIN код
                    # Гарантуємо, що для контейнерів та спецтехніки vin заповнений з serial_number, якщо vin порожній
                    vehicle_type_lower = vehicle_type.lower() if vehicle_type else ""
                    is_container = "контейнер" in vehicle_type_lower or "змінний кузов" in vehicle_type_lower
                    is_special_equipment = "спеціальн" in vehicle_type_lower or "спецтехніка" in vehicle_type_lower
                    vin = (vehicle.get("vin") or "").strip() or None
                    
                    if (is_container or is_special_equipment) and not vin and serial_number:
                        vin = serial_number
                    
                    # Числові поля
                    def safe_int(val):
                        try:
                            return int(float(val)) if val else None
                        except (ValueError, TypeError):
                            return None
                    
                    def safe_float(val):
                        try:
                            return float(val) if val else None
                        except (ValueError, TypeError):
                            return None
                    
                    gross_weight_kg = safe_int(vehicle.get("gross_weight_kg"))
                    net_weight_kg = safe_int(vehicle.get("net_weight_kg"))
                    payload_kg = safe_int(vehicle.get("payload_kg"))
                    engine_cm3 = safe_int(vehicle.get("engine_cm3"))
                    seats = safe_int(vehicle.get("seats"))
                    power_kw = safe_float(vehicle.get("power_kw"))
                    year_model = safe_int(vehicle.get("year_model"))
                    year_calendar = safe_int(vehicle.get("year_calendar"))
                    quantity = safe_float(vehicle.get("quantity"))
                    
                    cursor = await db.execute(
                        """
                        INSERT INTO vehicles (
                            processed_file_id, mrn, vin, model,
                            customs_value, create_at_ccd, pdf_url, payload_json, created_at,
                            vehicle_type, brand, uktzed, description, producer_country,
                            gross_weight, net_weight, gross_weight_kg, net_weight_kg,
                            payload_kg, engine_cm3, seats, power_kw, wheel_formula,
                            year_model, year_calendar, quantity, serial_number, unit_human
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            processed_id,
                            vehicle.get("mrn"),
                            vin,  # Використовуємо оброблений vin (з урахуванням контейнерів)
                            vehicle.get("model"),
                            vehicle.get("customs_value"),
                            vehicle.get("create_at_ccd"),
                            vehicle.get("pdf_url"),
                            payload_json,
                            current_time_iso(),
                            vehicle_type,
                            brand,
                            uktzed,
                            description,
                            producer_country,
                            gross_weight,
                            net_weight,
                            gross_weight_kg,
                            net_weight_kg,
                            payload_kg,
                            engine_cm3,
                            seats,
                            power_kw,
                            wheel_formula,
                            year_model,
                            year_calendar,
                            quantity,
                            serial_number,
                            unit_human,
                        ),
                    )
                    vehicle_id = cursor.lastrowid
                    if vehicle_id:
                        new_vehicle_ids.append(vehicle_id)
                    inserted_vehicles += 1

                await db.execute(
                    """
                    INSERT INTO sync_runs (
                        window_start, window_end, started_at, finished_at,
                        files_downloaded, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        window_start,
                        window_end,
                        started_at,
                        current_time_iso(),
                        inserted_files,
                        "success",
                        current_time_iso(),
                    ),
                )

                await db.commit()
            except Exception:
                await db.rollback()
                # Зберігаємо запис про помилку в окремій транзакції
                async with aiosqlite.connect(self.db_path) as error_db:
                    await error_db.execute("PRAGMA foreign_keys=ON;")
                    await error_db.execute(
                        """
                        INSERT INTO sync_runs (
                            window_start, window_end, started_at, finished_at,
                            files_downloaded, status, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            window_start,
                            window_end,
                            started_at,
                            current_time_iso(),
                            inserted_files,
                            "error",
                            current_time_iso(),
                        ),
                    )
                    await error_db.commit()
                raise

        return {
            "emails": len(email_cache),
            "files": inserted_files,
            "vehicles": inserted_vehicles,
            "new_vehicle_ids": new_vehicle_ids,  # ID нових vehicles для синхронізації з Trello
        }

    async def get_last_download_timestamp(self) -> Optional[str]:
        """Повертає ISO-час останнього збереженого файлу (для наступного запуску)."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT downloaded_at FROM processed_files ORDER BY downloaded_at DESC LIMIT 1"
            )
            row = await cursor.fetchone()
            if row:
                return row[0]
        return None

    async def get_last_successful_window(self) -> Optional[Tuple[str, str]]:
        """Повертає пару (window_start, window_end) останнього успішного запуску."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT window_start, window_end
                FROM sync_runs
                WHERE status = 'success'
                ORDER BY id DESC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()
            if row:
                return row[0], row[1]
        return None

    async def update_checked_emails(self, email_uids: List[Tuple[str, str]]) -> int:
        """
        Оновлює updated_at для перевірених email повідомлень.
        Використовується коли файли вже є в БД, але ми все одно перевіряємо email.
        
        Args:
            email_uids: Список кортежів (folder_name, message_uid)
        
        Returns:
            Кількість оновлених записів
        """
        if not email_uids:
            return 0
        
        await self.initialize()
        now_iso = current_time_iso()
        updated_count = 0
        
        async with aiosqlite.connect(self.db_path) as db:
            for folder_name, message_uid in email_uids:
                cursor = await db.execute(
                    """
                    UPDATE email_messages
                    SET updated_at = ?
                    WHERE folder_name = ? AND message_uid = ?
                    """,
                    (now_iso, folder_name, message_uid),
                )
                if cursor.rowcount > 0:
                    updated_count += 1
            await db.commit()
        
        return updated_count

    async def fetch_vehicles_missing_pdf(self) -> List[Dict]:
        """Повертає список транспортних засобів без pdf_url."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Використовуємо нормалізовані колонки
            cursor = await db.execute(
                """
                SELECT v.id, v.mrn, v.vin, v.model, v.brand, v.vehicle_type,
                       v.uktzed, v.description, pf.filename
                FROM vehicles v
                JOIN processed_files pf ON pf.id = v.processed_file_id
                WHERE v.pdf_url IS NULL OR v.pdf_url = ''
                """
            )
            rows = await cursor.fetchall()

        results: List[Dict] = []
        for row in rows:
            # Формуємо payload з нормалізованих колонок
            payload = {
                "mrn": row["mrn"],
                "vin": row["vin"],
                "model": row["model"],
                "brand": row["brand"],
                "vehicle_type": row["vehicle_type"],
                "uktzed": row["uktzed"],
                "description": row["description"],
            }
            results.append(
                {
                    "vehicle_id": row["id"],
                    "payload": payload,
                    "filename": row["filename"],
                }
            )
        return results

    async def bulk_update_pdf_urls(self, updates: Sequence[Tuple[int, str]]) -> int:
        """Оновлює pdf_url для списку транспортних засобів."""
        if not updates:
            return 0

        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.executemany(
                "UPDATE vehicles SET pdf_url = ? WHERE id = ?",
                [(url, vehicle_id) for vehicle_id, url in updates],
            )
            await db.commit()

        return len(updates)

    async def get_trello_card_by_vehicle_id(self, vehicle_id: int) -> Optional[Dict]:
        """Отримує інформацію про Trello картку за vehicle_id"""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trello_cards WHERE vehicle_id = ?",
                (vehicle_id,)
            )
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def save_trello_card(
        self,
        vehicle_id: int,
        trello_card_id: str,
        trello_list_id: str,
        status: str = "success",
        attachments: Optional[List[Dict]] = None,
        media_files: Optional[List[Dict]] = None,
        card_name: Optional[str] = None,
        description: Optional[str] = None,
        card_pos: Optional[float] = None,
        checklists: Optional[List[Dict]] = None,
        comments: Optional[List[Dict]] = None,
        trello_list_name: Optional[str] = None,
        labels: Optional[List[Dict]] = None,
        is_present: Optional[bool] = None,
        last_known_list_id: Optional[str] = None,
    ) -> int:
        """Зберігає або оновлює інформацію про Trello картку"""
        await self.initialize()
        now_iso = current_time_iso()
        
        attachments_json = json.dumps(attachments or [], ensure_ascii=False)
        media_files_json = json.dumps(media_files or [], ensure_ascii=False)
        checklists_json = json.dumps(checklists or [], ensure_ascii=False)
        comments_json = json.dumps(comments or [], ensure_ascii=False)
        labels_json = json.dumps(labels or [], ensure_ascii=False)
        
        async with aiosqlite.connect(self.db_path) as db:
            # Перевіряємо чи існує запис
            cursor = await db.execute(
                "SELECT id FROM trello_cards WHERE vehicle_id = ? OR trello_card_id = ?",
                (vehicle_id, trello_card_id)
            )
            existing = await cursor.fetchone()
            
            if existing:
                # Оновлюємо існуючий запис
                # Визначаємо значення для is_present та last_known_list_id
                update_is_present = is_present if is_present is not None else 1  # За замовчуванням true
                update_last_known_list_id = last_known_list_id if last_known_list_id is not None else trello_list_id
                
                await db.execute(
                    """
                    UPDATE trello_cards
                    SET vehicle_id = ?,
                        trello_card_id = ?,
                        trello_list_id = ?,
                        trello_list_name = ?,
                        card_name = ?,
                        description = ?,
                        card_pos = ?,
                        synced_at = ?,
                        last_sync_status = ?,
                        attachments_json = ?,
                        media_files_json = ?,
                        checklists_json = ?,
                        comments_json = ?,
                        labels_json = ?,
                        is_present = ?,
                        last_known_list_id = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        vehicle_id,
                        trello_card_id,
                        trello_list_id,
                        trello_list_name,
                        card_name,
                        description,
                        card_pos,
                        now_iso,
                        status,
                        attachments_json,
                        media_files_json,
                        checklists_json,
                        comments_json,
                        labels_json,
                        update_is_present,
                        update_last_known_list_id,
                        now_iso,
                        existing[0],
                    )
                )
                await db.commit()
                return existing[0]
            else:
                # Створюємо новий запис
                # Визначаємо значення для is_present та last_known_list_id
                insert_is_present = 1 if is_present is None else (1 if is_present else 0)
                insert_last_known_list_id = last_known_list_id if last_known_list_id is not None else trello_list_id
                
                cursor = await db.execute(
                    """
                    INSERT INTO trello_cards (
                        vehicle_id, trello_card_id, trello_list_id, trello_list_name,
                        card_name, description, card_pos,
                        synced_at, last_sync_status,
                        attachments_json, media_files_json,
                        checklists_json, comments_json, labels_json,
                        is_present, last_known_list_id,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        vehicle_id,
                        trello_card_id,
                        trello_list_id,
                        trello_list_name,
                        card_name,
                        description,
                        card_pos,
                        now_iso,
                        status,
                        attachments_json,
                        media_files_json,
                        checklists_json,
                        comments_json,
                        labels_json,
                        insert_is_present,
                        insert_last_known_list_id,
                        now_iso,
                        now_iso,
                    )
                )
                await db.commit()
                return cursor.lastrowid

    async def get_vehicle_by_id(self, vehicle_id: int) -> Optional[Dict]:
        """Отримує транспортний засіб за ID"""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM vehicles WHERE id = ?",
                (vehicle_id,)
            )
            row = await cursor.fetchone()
            if row:
                vehicle_dict = dict(row)
                # Парсимо payload_json
                if vehicle_dict.get("payload_json"):
                    try:
                        vehicle_dict["payload"] = json.loads(vehicle_dict["payload_json"])
                    except Exception:
                        vehicle_dict["payload"] = {}
                return vehicle_dict
            return None

    async def get_vehicles_by_ids(self, vehicle_ids: List[int]) -> List[Dict]:
        """Отримує транспортні засоби за списком ID (фільтрує по vehicle_type)"""
        if not vehicle_ids:
            return []
        
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            placeholders = ",".join("?" for _ in vehicle_ids)
            # Використовуємо нормалізовану колонку vehicle_type для фільтрації
            query = f"""
                SELECT v.id, v.mrn, v.vin, v.model, v.create_at_ccd, v.pdf_url, 
                       v.payload_json, v.created_at, v.vehicle_type, v.brand,
                       v.uktzed, v.description, v.producer_country, v.gross_weight,
                       v.net_weight, v.gross_weight_kg, v.net_weight_kg, v.payload_kg,
                       v.engine_cm3, v.seats, v.power_kw, v.wheel_formula,
                       v.year_model, v.year_calendar, v.quantity, v.serial_number, v.unit_human
                FROM vehicles v
                WHERE v.id IN ({placeholders})
                  AND v.vehicle_type IS NOT NULL
                  AND TRIM(v.vehicle_type) != ''
                  AND v.vehicle_type != 'Автомобіль легковий'
            """
            
            cursor = await db.execute(query, vehicle_ids)
            rows = await cursor.fetchall()
            
            vehicles = []
            for row in rows:
                # Формуємо payload з нормалізованих колонок
                payload = {
                    "vehicle_type": row["vehicle_type"],
                    "brand": row["brand"],
                    "model": row["model"],
                    "vin": row["vin"],
                    "mrn": row["mrn"],
                    "uktzed": row["uktzed"],
                    "description": row["description"],
                    "producer_country": row["producer_country"],
                    "gross_weight": row["gross_weight"],
                    "net_weight": row["net_weight"],
                    "gross_weight_kg": row["gross_weight_kg"],
                    "net_weight_kg": row["net_weight_kg"],
                    "payload_kg": row["payload_kg"],
                    "engine_cm3": row["engine_cm3"],
                    "seats": row["seats"],
                    "power_kw": row["power_kw"],
                    "wheel_formula": row["wheel_formula"],
                    "year_model": row["year_model"],
                    "year_calendar": row["year_calendar"],
                    "quantity": row["quantity"],
                    "serial_number": row["serial_number"],
                    "unit_human": row["unit_human"],
                    "create_at_ccd": row["create_at_ccd"],
                    "customs_value": None,  # Можна додати якщо потрібно
                }
                vehicles.append({
                    "id": row["id"],
                    "mrn": row["mrn"],
                    "vin": row["vin"],
                    "model": row["model"],
                    "brand": row["brand"],  # Додаємо brand на верхній рівень
                    "vehicle_type": row["vehicle_type"],  # Додаємо vehicle_type на верхній рівень
                    "description": row["description"],  # Додаємо description на верхній рівень
                    "create_at_ccd": row["create_at_ccd"],
                    "pdf_url": row["pdf_url"],
                    "payload": payload,
                    "created_at": row["created_at"],
                })
            
            return vehicles

    async def get_vehicles_by_vins(self, vins: List[str]) -> List[Dict]:
        """Отримує транспортні засоби за списком VIN (ігнорує легкові авто)"""
        if not vins:
            return []

        normalized_vins = []
        seen = set()
        for vin in vins:
            if not vin:
                continue
            cleaned = vin.strip().upper()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                normalized_vins.append(cleaned)

        if not normalized_vins:
            return []

        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row

            placeholders = ",".join("?" for _ in normalized_vins)
            # Використовуємо нормалізовану колонку vehicle_type для фільтрації
            query = f"""
                SELECT v.id, v.mrn, v.vin, v.model, v.create_at_ccd, v.pdf_url, 
                       v.payload_json, v.created_at, v.vehicle_type, v.brand,
                       v.uktzed, v.description, v.producer_country, v.gross_weight,
                       v.net_weight, v.gross_weight_kg, v.net_weight_kg, v.payload_kg,
                       v.engine_cm3, v.seats, v.power_kw, v.wheel_formula,
                       v.year_model, v.year_calendar, v.quantity, v.serial_number, v.unit_human
                FROM vehicles v
                WHERE UPPER(v.vin) IN ({placeholders})
                  AND v.vehicle_type IS NOT NULL
                  AND TRIM(v.vehicle_type) != ''
                  AND v.vehicle_type != 'Автомобіль легковий'
            """

            cursor = await db.execute(query, normalized_vins)
            rows = await cursor.fetchall()

            vehicles = []
            for row in rows:
                # Формуємо payload з нормалізованих колонок
                payload = {
                    "vehicle_type": row["vehicle_type"],
                    "brand": row["brand"],
                    "model": row["model"],
                    "vin": row["vin"],
                    "mrn": row["mrn"],
                    "uktzed": row["uktzed"],
                    "description": row["description"],
                    "producer_country": row["producer_country"],
                    "gross_weight": row["gross_weight"],
                    "net_weight": row["net_weight"],
                    "gross_weight_kg": row["gross_weight_kg"],
                    "net_weight_kg": row["net_weight_kg"],
                    "payload_kg": row["payload_kg"],
                    "engine_cm3": row["engine_cm3"],
                    "seats": row["seats"],
                    "power_kw": row["power_kw"],
                    "wheel_formula": row["wheel_formula"],
                    "year_model": row["year_model"],
                    "year_calendar": row["year_calendar"],
                    "quantity": row["quantity"],
                    "serial_number": row["serial_number"],
                    "unit_human": row["unit_human"],
                    "create_at_ccd": row["create_at_ccd"],
                }
                vehicles.append({
                    "id": row["id"],
                    "mrn": row["mrn"],
                    "vin": row["vin"],
                    "model": row["model"],
                    "brand": row["brand"],  # Додаємо brand на верхній рівень
                    "vehicle_type": row["vehicle_type"],  # Додаємо vehicle_type на верхній рівень
                    "description": row["description"],  # Додаємо description на верхній рівень
                    "create_at_ccd": row["create_at_ccd"],
                    "pdf_url": row["pdf_url"],
                    "payload": payload,
                    "created_at": row["created_at"],
                })
            
            return vehicles

    async def get_vehicles_for_trello_sync(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        exclude_synced: bool = True,
    ) -> List[Dict]:
        """
        Отримує список транспортних засобів для синхронізації з Trello
        
        Args:
            date_from: Дата початку (ISO формат) - тільки vehicles з create_at_ccd >= date_from
            date_to: Дата кінця (ISO формат) - тільки vehicles з create_at_ccd <= date_to
            exclude_synced: Якщо True, виключає vehicles які вже синхронізовані з Trello
        """
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Використовуємо нормалізовану колонку vehicle_type для фільтрації
            query = """
                SELECT v.id, v.mrn, v.vin, v.model, v.create_at_ccd, v.pdf_url, 
                       v.payload_json, v.created_at, v.vehicle_type, v.brand,
                       v.uktzed, v.description, v.producer_country, v.gross_weight,
                       v.net_weight, v.gross_weight_kg, v.net_weight_kg, v.payload_kg,
                       v.engine_cm3, v.seats, v.power_kw, v.wheel_formula,
                       v.year_model, v.year_calendar, v.quantity, v.serial_number, v.unit_human
                FROM vehicles v
                WHERE v.vehicle_type IS NOT NULL
                  AND TRIM(v.vehicle_type) != ''
                  AND v.vehicle_type != 'Автомобіль легковий'
            """
            params = []
            
            if date_from:
                date_from_date_only = date_from[:10] if len(date_from) >= 10 else date_from
                query += """
                    AND (
                        (v.create_at_ccd IS NOT NULL AND v.create_at_ccd >= ?)
                        OR (DATE(v.created_at) >= ?)
                    )
                """
                params.extend([date_from_date_only, date_from_date_only])

            if date_to:
                date_to_date_only = date_to[:10] if len(date_to) >= 10 else date_to
                query += """
                    AND (
                        (v.create_at_ccd IS NOT NULL AND v.create_at_ccd <= ?)
                        OR (DATE(v.created_at) <= ?)
                    )
                """
                params.extend([date_to_date_only, date_to_date_only])
            
            if exclude_synced:
                query += """
                    AND NOT EXISTS (
                        SELECT 1
                        FROM trello_cards tc
                        WHERE tc.vehicle_id = v.id
                          AND tc.trello_card_id IS NOT NULL
                          AND TRIM(tc.trello_card_id) != ''
                    )
                """
            
            query += """
                ORDER BY
                    CASE WHEN v.create_at_ccd IS NOT NULL THEN v.create_at_ccd ELSE DATE(v.created_at) END ASC,
                    v.created_at ASC
            """
            
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            
            vehicles = []
            for row in rows:
                # Формуємо payload з нормалізованих колонок
                payload = {
                    "vehicle_type": row["vehicle_type"],
                    "brand": row["brand"],
                    "model": row["model"],
                    "vin": row["vin"],
                    "mrn": row["mrn"],
                    "uktzed": row["uktzed"],
                    "description": row["description"],
                    "producer_country": row["producer_country"],
                    "gross_weight": row["gross_weight"],
                    "net_weight": row["net_weight"],
                    "gross_weight_kg": row["gross_weight_kg"],
                    "net_weight_kg": row["net_weight_kg"],
                    "payload_kg": row["payload_kg"],
                    "engine_cm3": row["engine_cm3"],
                    "seats": row["seats"],
                    "power_kw": row["power_kw"],
                    "wheel_formula": row["wheel_formula"],
                    "year_model": row["year_model"],
                    "year_calendar": row["year_calendar"],
                    "quantity": row["quantity"],
                    "serial_number": row["serial_number"],
                    "unit_human": row["unit_human"],
                    "create_at_ccd": row["create_at_ccd"],
                }
                vehicles.append({
                    "id": row["id"],
                    "mrn": row["mrn"],
                    "vin": row["vin"],
                    "model": row["model"],
                    "brand": row["brand"],  # Додаємо brand на верхній рівень
                    "vehicle_type": row["vehicle_type"],  # Додаємо vehicle_type на верхній рівень
                    "description": row["description"],  # Додаємо description на верхній рівень
                    "create_at_ccd": row["create_at_ccd"],
                    "pdf_url": row["pdf_url"],
                    "payload": payload,
                    "created_at": row["created_at"],
                })
            
            return vehicles

    async def get_trello_summary(self) -> Dict[str, Optional[int]]:
        """Повертає агреговану статистику по Trello синхронізації."""
        await self.initialize()
        summary = {
            "total_valid_vehicles": 0,
            "vehicles_without_trello": 0,
            "total_trello_cards": 0,
            "failed_trello_cards": 0,
            "latest_sync": None,
        }

        async with aiosqlite.connect(self.db_path) as db:
            # Використовуємо нормалізовану колонку vehicle_type
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM vehicles
                WHERE vehicle_type IS NOT NULL
                  AND TRIM(vehicle_type) != ''
                """
            )
            summary["total_valid_vehicles"] = (await cursor.fetchone() or [0])[0]

            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM vehicles v
                WHERE v.vehicle_type IS NOT NULL
                  AND TRIM(v.vehicle_type) != ''
                  AND NOT EXISTS (
                      SELECT 1 FROM trello_cards tc WHERE tc.vehicle_id = v.id
                  )
                """
            )
            summary["vehicles_without_trello"] = (await cursor.fetchone() or [0])[0]

            cursor = await db.execute("SELECT COUNT(*) FROM trello_cards")
            summary["total_trello_cards"] = (await cursor.fetchone() or [0])[0]

            cursor = await db.execute(
                "SELECT COUNT(*) FROM trello_cards WHERE trello_card_id IS NULL OR trello_card_id = ''"
            )
            summary["failed_trello_cards"] = (await cursor.fetchone() or [0])[0]

            cursor = await db.execute("SELECT MAX(synced_at) FROM trello_cards")
            summary["latest_sync"] = (await cursor.fetchone() or [None])[0]

        return summary

    async def get_orphan_trello_cards(self) -> List[Dict]:
        """Повертає Trello картки, які посилаються на відсутні записи vehicles."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT tc.*
                FROM trello_cards tc
                LEFT JOIN vehicles v ON v.id = tc.vehicle_id
                WHERE v.id IS NULL
                ORDER BY tc.updated_at DESC
                """
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_trello_cards_by_vehicle_types(self, vehicle_types: Sequence[str]) -> List[Dict]:
        """Повертає Trello картки, що відповідають вказаним типам vehicle_type."""
        if not vehicle_types:
            return []

        await self.initialize()
        placeholders = ",".join("?" for _ in vehicle_types)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Використовуємо нормалізовану колонку vehicle_type
            cursor = await db.execute(
                f"""
                SELECT tc.*, v.vehicle_type
                FROM trello_cards tc
                JOIN vehicles v ON v.id = tc.vehicle_id
                WHERE TRIM(v.vehicle_type) IN ({placeholders})
                """,
                list(vehicle_types),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_trello_card_record(
        self,
        *,
        vehicle_id: Optional[int] = None,
        trello_card_id: Optional[str] = None,
    ) -> int:
        """Видаляє запис про Trello картку з БД."""
        if vehicle_id is None and not trello_card_id:
            return 0

        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            if vehicle_id is not None and trello_card_id:
                cursor = await db.execute(
                    "DELETE FROM trello_cards WHERE vehicle_id = ? OR trello_card_id = ?",
                    (vehicle_id, trello_card_id),
                )
            elif vehicle_id is not None:
                cursor = await db.execute(
                    "DELETE FROM trello_cards WHERE vehicle_id = ?",
                    (vehicle_id,),
                )
            else:
                cursor = await db.execute(
                    "DELETE FROM trello_cards WHERE trello_card_id = ?",
                    (trello_card_id,),
                )
            await db.commit()
            return cursor.rowcount

    async def cleanup_empty_trello_records(self) -> int:
        """Видаляє записи trello_cards без коректного trello_card_id."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM trello_cards WHERE trello_card_id IS NULL OR TRIM(trello_card_id) = ''"
            )
            await db.commit()
            return cursor.rowcount

    async def get_all_trello_cards_with_ids(self, include_archived: bool = True) -> List[Dict]:
        """
        Отримує всі записи trello_cards з наявним trello_card_id.
        
        Args:
            include_archived: Якщо False, пропускає архівовані картки (is_archived = 1)
        """
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            query = """
                SELECT * FROM trello_cards 
                WHERE trello_card_id IS NOT NULL 
                  AND TRIM(trello_card_id) != ''
            """
            
            if not include_archived:
                query += " AND (is_archived IS NULL OR is_archived = 0)"
            
            query += " ORDER BY id"
            
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_trello_card_presence(
        self,
        trello_card_id: str,
        is_present: bool,
        current_list_id: Optional[str] = None,
        is_archived: Optional[bool] = None,
    ) -> bool:
        """
        Оновлює статус наявності та архівації картки в Trello.
        
        Args:
            trello_card_id: ID картки в Trello
            is_present: Чи існує картка в Trello
            current_list_id: Поточний список картки (опціонально)
            is_archived: Чи картка архівована (closed в Trello API)
        """
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            is_present_int = 1 if is_present else 0
            is_archived_int = 1 if is_archived else 0 if is_archived is not None else None
            
            if current_list_id and is_archived_int is not None:
                # Оновлюємо всі поля
                cursor = await db.execute(
                    """
                    UPDATE trello_cards
                    SET is_present = ?,
                        last_known_list_id = ?,
                        is_archived = ?,
                        updated_at = ?
                    WHERE trello_card_id = ?
                    """,
                    (is_present_int, current_list_id, is_archived_int, current_time_iso(), trello_card_id)
                )
            elif current_list_id:
                # Оновлюємо is_present та last_known_list_id
                cursor = await db.execute(
                    """
                    UPDATE trello_cards
                    SET is_present = ?,
                        last_known_list_id = ?,
                        updated_at = ?
                    WHERE trello_card_id = ?
                    """,
                    (is_present_int, current_list_id, current_time_iso(), trello_card_id)
                )
            elif is_archived_int is not None:
                # Оновлюємо is_present та is_archived
                cursor = await db.execute(
                    """
                    UPDATE trello_cards
                    SET is_present = ?,
                        is_archived = ?,
                        updated_at = ?
                    WHERE trello_card_id = ?
                    """,
                    (is_present_int, is_archived_int, current_time_iso(), trello_card_id)
                )
            else:
                # Оновлюємо тільки is_present
                cursor = await db.execute(
                    """
                    UPDATE trello_cards
                    SET is_present = ?,
                        updated_at = ?
                    WHERE trello_card_id = ?
                    """,
                    (is_present_int, current_time_iso(), trello_card_id)
                )
            await db.commit()
            return cursor.rowcount > 0

    async def get_vehicle_type_by_id(self, vehicle_id: int) -> Optional[str]:
        """Повертає vehicle_type для заданого vehicle_id."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            # Використовуємо нормалізовану колонку vehicle_type
            cursor = await db.execute(
                "SELECT vehicle_type FROM vehicles WHERE id = ?",
                (vehicle_id,),
            )
            row = await cursor.fetchone()
        if not row or not row[0]:
            return None
        vehicle_type = (row[0] or "").strip()
        return vehicle_type or None

    async def _migrate_trello_cards_table(self, db):
        """Міграція таблиці trello_cards: додає нові колонки якщо їх немає"""
        try:
            # Перевіряємо які колонки вже існують
            cursor = await db.execute("PRAGMA table_info(trello_cards)")
            columns = await cursor.fetchall()
            existing_columns = {col[1] for col in columns}  # col[1] - це назва колонки
            
            # Список нових колонок для додавання
            new_columns = {
                "card_name": "TEXT",
                "description": "TEXT",
                "card_pos": "REAL",
                "checklists_json": "TEXT",
                "comments_json": "TEXT",
                "trello_list_name": "TEXT",
                "labels_json": "TEXT",
                "is_present": "INTEGER DEFAULT 1",  # 1 = true, 0 = false (SQLite boolean)
                "last_known_list_id": "TEXT",
                "is_archived": "INTEGER DEFAULT 0",  # 1 = archived in Trello (closed: true)
            }
            
            # Додаємо колонки яких немає
            for col_name, col_type in new_columns.items():
                if col_name not in existing_columns:
                    try:
                        await db.execute(f"ALTER TABLE trello_cards ADD COLUMN {col_name} {col_type}")
                        logger.info(f"Added column {col_name} to trello_cards table")
                    except Exception as e:
                        logger.warning(f"Failed to add column {col_name}: {e}")
            
            await db.commit()
        except Exception as e:
            logger.warning(f"Error during trello_cards migration: {e}")

    async def get_last_sync_run(self) -> Optional[Dict]:
        """Повертає інформацію про останній запис у sync_runs."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT status, window_start, window_end,
                       started_at, finished_at, files_downloaded, created_at
                FROM sync_runs
                ORDER BY id DESC
                LIMIT 1
                """
            )
            row = await cursor.fetchone()

        if not row:
            return None

        keys = [
            "status",
            "window_start",
            "window_end",
            "started_at",
            "finished_at",
            "files_downloaded",
            "created_at",
        ]
        return dict(zip(keys, row))

    # ==================== Trello Labels Methods ====================
    
    async def get_trello_label_id(self, vehicle_type: str) -> Optional[str]:
        """
        Отримує ID мітки Trello для заданого типу авто з БД.
        Шукає як за точним співпадінням, так і за нормалізованим (без урахування регістру).
        """
        if not vehicle_type or not vehicle_type.strip():
            return None
        
        await self.initialize()
        vehicle_type_clean = vehicle_type.strip()
        
        # Нормалізуємо для порівняння (приводимо до нижнього регістру)
        vehicle_type_normalized = vehicle_type_clean.lower()
        
        async with aiosqlite.connect(self.db_path) as db:
            # Спочатку шукаємо за точним співпадінням
            cursor = await db.execute(
                "SELECT trello_label_id FROM trello_labels WHERE vehicle_type = ?",
                (vehicle_type_clean,)
            )
            row = await cursor.fetchone()
            if row:
                return row[0]
            
            # Якщо не знайдено, шукаємо за нормалізованим (case-insensitive)
            # Отримуємо всі мітки та порівнюємо в Python (для коректної роботи з кирилицею)
            cursor = await db.execute(
                "SELECT vehicle_type, trello_label_id FROM trello_labels"
            )
            rows = await cursor.fetchall()
            for row in rows:
                db_vehicle_type = row[0]
                if db_vehicle_type and db_vehicle_type.lower() == vehicle_type_normalized:
                    return row[1]
            
            return None
    
    async def save_trello_label(
        self,
        vehicle_type: str,
        trello_label_id: str,
        label_name: Optional[str] = None,
        label_color: Optional[str] = None,
    ) -> bool:
        """Зберігає або оновлює мітку Trello в БД"""
        await self.initialize()
        now = current_time_iso()
        async with aiosqlite.connect(self.db_path) as db:
            # Перевіряємо чи існує запис
            cursor = await db.execute(
                "SELECT id FROM trello_labels WHERE vehicle_type = ?",
                (vehicle_type.strip(),)
            )
            existing = await cursor.fetchone()
            
            if existing:
                # Оновлюємо існуючий запис
                await db.execute(
                    """
                    UPDATE trello_labels
                    SET trello_label_id = ?,
                        label_name = ?,
                        label_color = ?,
                        updated_at = ?
                    WHERE vehicle_type = ?
                    """,
                    (trello_label_id, label_name, label_color, now, vehicle_type.strip())
                )
            else:
                # Створюємо новий запис
                await db.execute(
                    """
                    INSERT INTO trello_labels 
                    (vehicle_type, trello_label_id, label_name, label_color, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (vehicle_type.strip(), trello_label_id, label_name, label_color, now, now)
                )
            await db.commit()
            return True
    
    async def get_all_vehicle_types(self) -> List[str]:
        """Отримує список всіх унікальних типів авто з БД"""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            # Використовуємо нормалізовану колонку vehicle_type
            cursor = await db.execute(
                """
                SELECT DISTINCT vehicle_type
                FROM vehicles
                WHERE vehicle_type IS NOT NULL
                  AND TRIM(vehicle_type) != ''
                ORDER BY vehicle_type
                """
            )
            rows = await cursor.fetchall()
            return [row[0].strip() for row in rows if row[0] and row[0].strip()]
    
    async def get_vehicle_types_without_labels(self) -> List[str]:
        """Отримує список типів авто, які не мають міток Trello"""
        await self.initialize()
        all_types = await self.get_all_vehicle_types()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT vehicle_type FROM trello_labels")
            existing_types = {row[0].strip().lower() for row in await cursor.fetchall() if row[0]}
        
        # Нормалізуємо типи та видаляємо дублікати
        normalized_existing = {vt.lower() for vt in existing_types}
        result = []
        seen_normalized = set()
        
        for vt in all_types:
            if not vt or not vt.strip():
                continue
            normalized = vt.strip().lower()
            # Перевіряємо чи є мітка для цього типу (з урахуванням регістру)
            if normalized not in normalized_existing and normalized not in seen_normalized:
                # Використовуємо оригінальний тип з правильним регістром
                # (перша літера велика, решта як в оригіналі)
                if len(vt.strip()) > 1:
                    normalized_type = vt.strip()[0].upper() + vt.strip()[1:]
                else:
                    normalized_type = vt.strip().upper()
                result.append(normalized_type)
                seen_normalized.add(normalized)
        
        return result
    
    async def get_all_trello_labels(self) -> List[Dict]:
        """Отримує всі мітки Trello з БД"""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM trello_labels ORDER BY vehicle_type"
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # ==================== ЗВІТИ ====================
    
    async def get_vmd_count_by_date_range(
        self,
        date_from: str,
        date_to: str,
        vehicle_type_filter: Optional[str] = None
    ) -> Dict:
        """
        Отримує кількість ВМД за вказаний період.
        
        Args:
            date_from: Дата початку (формат: YYYY-MM-DD)
            date_to: Дата кінця (формат: YYYY-MM-DD)
            vehicle_type_filter: Опціональний фільтр по типу авто
        
        Returns:
            Dict з загальною кількістю та розбивкою по типах
        """
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Базовий запит - використовуємо нормалізовану колонку vehicle_type
            query = """
                SELECT 
                    vehicle_type,
                    COUNT(*) as count
                FROM vehicles
                WHERE (
                      (create_at_ccd IS NOT NULL AND create_at_ccd >= ? AND create_at_ccd <= ?)
                      OR (create_at_ccd IS NULL AND DATE(created_at) >= ? AND DATE(created_at) <= ?)
                  )
            """
            params = [date_from, date_to, date_from, date_to]
            
            if vehicle_type_filter:
                query += """
                    AND vehicle_type = ?
                """
                params.append(vehicle_type_filter)
            
            query += """
                GROUP BY vehicle_type
                ORDER BY count DESC
            """
            
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            
            # Формуємо результат
            total = 0
            by_type = {}
            for row in rows:
                vtype = row["vehicle_type"] or "Не визначено"
                count = row["count"]
                by_type[vtype] = count
                total += count
            
            return {
                "total": total,
                "by_type": by_type,
                "date_from": date_from,
                "date_to": date_to
            }
    
    async def get_vmd_stats_summary(self) -> Dict:
        """
        Отримує загальну статистику по ВМД.
        
        Returns:
            Dict з загальною кількістю, першою та останньою датою
        """
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Загальна кількість
            cursor = await db.execute(
                "SELECT COUNT(*) as total FROM vehicles WHERE payload_json IS NOT NULL"
            )
            total_row = await cursor.fetchone()
            total = total_row["total"] if total_row else 0
            
            # Перша та остання дата ВМД
            cursor = await db.execute("""
                SELECT 
                    MIN(COALESCE(create_at_ccd, DATE(created_at))) as first_date,
                    MAX(COALESCE(create_at_ccd, DATE(created_at))) as last_date
                FROM vehicles
                WHERE payload_json IS NOT NULL
            """)
            date_row = await cursor.fetchone()
            first_date = date_row["first_date"] if date_row else None
            last_date = date_row["last_date"] if date_row else None
            
            # Кількість по типах (загальна) - використовуємо нормалізовану колонку
            cursor = await db.execute("""
                SELECT 
                    vehicle_type,
                    COUNT(*) as count
                FROM vehicles
                GROUP BY vehicle_type
                ORDER BY count DESC
            """)
            type_rows = await cursor.fetchall()
            
            by_type = {}
            for row in type_rows:
                vtype = row["vehicle_type"] or "Не визначено"
                by_type[vtype] = row["count"]
            
            return {
                "total": total,
                "first_date": first_date,
                "last_date": last_date,
                "by_type": by_type
            }
    
    async def get_vmd_list_by_date_range(
        self,
        date_from: str,
        date_to: str,
        limit: int = 100
    ) -> List[Dict]:
        """
        Отримує список ВМД за вказаний період.
        
        Args:
            date_from: Дата початку (формат: YYYY-MM-DD)
            date_to: Дата кінця (формат: YYYY-MM-DD)
            limit: Максимальна кількість записів
        
        Returns:
            Список ВМД з основними даними
        """
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Використовуємо нормалізовані колонки
            query = """
                SELECT 
                    id,
                    mrn,
                    vin,
                    model,
                    brand,
                    vehicle_type,
                    create_at_ccd
                FROM vehicles
                WHERE (
                      (create_at_ccd IS NOT NULL AND create_at_ccd >= ? AND create_at_ccd <= ?)
                      OR (create_at_ccd IS NULL AND DATE(created_at) >= ? AND DATE(created_at) <= ?)
                  )
                ORDER BY 
                    COALESCE(create_at_ccd, DATE(created_at)) DESC,
                    created_at DESC
                LIMIT ?
            """
            
            cursor = await db.execute(query, [date_from, date_to, date_from, date_to, limit])
            rows = await cursor.fetchall()
            
            results = []
            for row in rows:
                    results.append({
                        "id": row["id"],
                        "mrn": row["mrn"],
                        "vin": row["vin"],
                        "model": row["model"],
                        "create_at_ccd": row["create_at_ccd"],
                    "vehicle_type": row["vehicle_type"] or "",
                    "brand": row["brand"] or "",
                    })
            
            return results


