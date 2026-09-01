#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Експортер ВМД даних в Excel
"""

import os
import json
import sqlite3
import pandas as pd
import logging
from typing import List, Dict, Optional, Sequence

from ..config import EXTRACT_DATA_DIR, LOCAL_TZ
from .database import VMDDatabase
from ..utils.helpers import clean_num

logger = logging.getLogger(__name__)


class ExcelExporter:
    """Експортер даних ВМД в Excel"""

    def __init__(self, output_dir: str = None, database: Optional[VMDDatabase] = None):
        if output_dir is None:
            output_dir = str(EXTRACT_DATA_DIR)
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        self.database = database
    
    def export_to_excel(self, data: List[Dict], filename: Optional[str] = None) -> str:
        """Експорт даних в Excel файл"""
        try:
            if not data:
                logger.warning("No data to export")
                return None
            
            df = pd.DataFrame(data)
            df = self._prepare_vehicle_dataframe(df)
            
            # Генеруємо ім'я файлу
            if not filename:
                filename = "vmd_extracted.xlsx"
            
            output_path = os.path.join(self.output_dir, filename)
            
            # Зберігаємо в Excel
            df.to_excel(output_path, index=False, engine='openpyxl')
            
            logger.info(f"Exported {len(df)} records to {output_path}")
            
            # Статистика
            logger.info(f"Export statistics:")
            logger.info(f"  Total records: {len(df)}")
            logger.info(f"  Columns: {len(df.columns)}")
            
            key_fields = {
                "mrn": "MRN",
                "brand": "Марка",
                "model": "Модель",
                "vin": "VIN",
                "customs_value": "Митна вартість",
                "create_at_ccd": "Дата ВМД"
            }
            
            for col, description in key_fields.items():
                if col in df.columns:
                    filled = df[col].notna().sum()
                    logger.info(f"  {description}: {filled}/{len(df)} ({filled/len(df)*100:.1f}%)")
            
            return output_path

        except Exception as e:
            logger.error(f"Error exporting to Excel: {e}")
            return None

    def _format_datetime_columns(self, df: pd.DataFrame, columns: Sequence[str]):
        """Форматує datetime колонки для Excel з урахуванням часових поясів."""
        if df.empty:
            return
        
        for col in columns:
            if col not in df.columns:
                continue
            
            try:
                # Парсимо дати з урахуванням UTC для уникнення попереджень про мішані часові пояси
                # Приховуємо попередження про формат дати
                import warnings
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=UserWarning, message=".*Could not infer format.*")
                    warnings.filterwarnings("ignore", category=UserWarning, message=".*parsed individually.*")
                    parsed = pd.to_datetime(df[col], errors="coerce", utc=True)
                
                # Перевіряємо, чи є валідні дати
                if not parsed.notna().any():
                    continue
                
                # Конвертуємо в локальний часовий пояс (utc=True завжди повертає UTC)
                try:
                    # Якщо parsed має часовий пояс (завжди так при utc=True), конвертуємо
                    if parsed.dt.tz is not None:
                        parsed = parsed.dt.tz_convert(LOCAL_TZ)
                    else:
                        # Якщо чомусь немає часового поясу, вважаємо UTC
                        parsed = parsed.dt.tz_localize("UTC", nonexistent="NaT", ambiguous="NaT")
                        parsed = parsed.dt.tz_convert(LOCAL_TZ)
                except (TypeError, AttributeError, ValueError) as tz_err:
                    # Якщо не вдалося конвертувати часовий пояс, залишаємо як є
                    logger.debug(f"Failed to convert timezone for column '{col}': {tz_err}")
                
                # Форматуємо для Excel
                df[col] = parsed.dt.strftime("%Y-%m-%d %H:%M:%S").where(parsed.notna(), df[col])
            except Exception as e:
                # Якщо помилка при обробці колонки, залишаємо оригінальні значення
                logger.debug(f"Failed to format datetime column '{col}': {e}")
                continue

    def _format_date_columns(self, df: pd.DataFrame, columns: Sequence[str]):
        """Форматує date колонки для Excel."""
        if df.empty:
            return
        
        for col in columns:
            if col not in df.columns:
                continue
            
            try:
                # Парсимо дати
                parsed = pd.to_datetime(df[col], errors="coerce", utc=True)
                
                # Перевіряємо, чи є валідні дати
                if not parsed.notna().any():
                    continue
                
                # Форматуємо для Excel (тільки дата, без часу)
                df[col] = parsed.dt.strftime("%Y-%m-%d").where(parsed.notna(), df[col])
            except Exception as e:
                # Якщо помилка при обробці колонки, залишаємо оригінальні значення
                logger.debug(f"Failed to format date column '{col}': {e}")
                continue

    def _prepare_vehicle_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Уніфікована нормалізація та порядок колонок для таблиці vehicles."""
        if df.empty:
            return df

        df = df.copy()
        df = df.drop(columns=["source_file"], errors="ignore")

        drop_columns = [
            "invoice_name",
            "vat_percent",
            "vat_amount_uah",
            "trademark",
            "producer",
            "origin_country",
        ]
        df = df.drop(columns=[c for c in drop_columns if c in df.columns], errors="ignore")

        column_order = [
            "id", "processed_file_id",
            "mrn", "uktzed", "description",
            "brand", "model", "year_model", "year_calendar", "vin", "serial_number",
            "engine_cm3", "power_kw", "seats", "wheel_formula",
            "payload_kg", "gross_weight_kg",
            "producer_country",
            "quantity", "unit_human",
            "gross_weight", "net_weight",
            "customs_value",
            "vehicle_type", "pdf_url", "brief_pdf_path",
            "create_at_ccd",
            "created_at",
        ]
        ordered_cols = [c for c in column_order if c in df.columns]
        other_cols = [c for c in df.columns if c not in column_order]
        df = df[ordered_cols + sorted(other_cols)]

        # Перейменовуємо vin в "VIN / SN" тільки якщо serial_number відсутній
        # Якщо serial_number присутній, залишаємо обидві колонки окремо
        if "vin" in df.columns and "serial_number" not in df.columns:
            df = df.rename(columns={"vin": "vin / sn"})
        elif "vin" in df.columns:
            df = df.rename(columns={"vin": "VIN"})

        numeric_cols = [
            "gross_weight", "net_weight", "quantity", "customs_value",
            "engine_cm3", "power_kw",
            "seats", "payload_kg", "gross_weight_kg", "year_model", "year_calendar"
        ]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].apply(clean_num)

        return df

    def export_all_tables(
        self,
        filename: Optional[str] = None,
        tables: Optional[Sequence[str]] = None,
    ) -> Optional[str]:
        """
        Експортує всі таблиці з БД у один Excel (кожна таблиця = окремий аркуш).
        """
        if not self.database:
            logger.error("Database instance is required to export all tables.")
            return None

        if not filename:
            filename = "vmd_full_export.xlsx"

        if not tables:
            tables = ("vehicles", "processed_files", "email_messages", "sync_runs", "trello_cards", "trello_labels", "briefs")

        output_path = os.path.join(self.output_dir, filename)

        try:
            conn = sqlite3.connect(self.database.db_path)
        except Exception as conn_err:
            logger.error(f"Cannot open database for export: {conn_err}")
            return None

        datetime_columns_map = {
            "email_messages": ["sent_at", "created_at", "updated_at"],
            "processed_files": ["downloaded_at", "window_started_at", "window_ended_at", "created_at"],
            "vehicles": ["created_at"],
            "sync_runs": ["window_start", "window_end", "started_at", "finished_at", "created_at"],
            "trello_cards": ["synced_at", "created_at", "updated_at"],
            "trello_labels": ["created_at", "updated_at"],
            "briefs": ["created_at", "updated_at"],
        }
        date_columns_map = {
            "vehicles": ["create_at_ccd"],
        }

        try:
            with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
                for table in tables:
                    try:
                        df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
                    except Exception as read_err:
                        logger.warning(f"Failed to read table '{table}': {read_err}")
                        df = pd.DataFrame()

                    if table == "vehicles":
                        # Перевіряємо чи є нормалізовані колонки
                        has_normalized = "vehicle_type" in df.columns and "brand" in df.columns
                        
                        if has_normalized:
                            # Використовуємо нормалізовані колонки - видаляємо payload_json
                            df = df.drop(columns=["payload_json"], errors="ignore")
                            df = df.drop(columns=["source_file"], errors="ignore")
                            df = self._prepare_vehicle_dataframe(df)
                        elif "payload_json" in df.columns:
                            # Fallback: розпаковуємо payload_json (для старих даних)
                            try:
                                payload_series = df["payload_json"].fillna("").apply(
                                    lambda x: json.loads(x) if x else {}
                                )
                                payload_df = pd.json_normalize(payload_series)
                                payload_df = payload_df.drop(columns=["pdf_url"], errors="ignore")

                                base_cols = [col for col in ["id", "processed_file_id", "pdf_url", "brief_pdf_path", "created_at"] if col in df.columns]
                                base_df = df[base_cols].copy() if base_cols else pd.DataFrame()

                                df = pd.concat([base_df.reset_index(drop=True), payload_df.reset_index(drop=True)], axis=1)
                                df = df.drop(columns=["source_file"], errors="ignore")
                                df = self._prepare_vehicle_dataframe(df)
                                
                            except Exception as json_err:
                                logger.warning(f"Failed to expand payload_json: {json_err}")

                    if table == "briefs":
                        # Обробка таблиці briefs - розпаковуємо images_json
                        try:
                            if "images_json" in df.columns:
                                # Розпаковуємо JSON в читабельний формат
                                def _format_images_json(value: Optional[str]) -> str:
                                    try:
                                        if not value:
                                            return ""
                                        images = json.loads(value) if isinstance(value, str) else value
                                        if isinstance(images, list):
                                            # Показуємо кількість фото та їх назви
                                            count = len(images)
                                            names = [os.path.basename(img) for img in images if img]
                                            if names:
                                                return f"{count} фото: {', '.join(names[:5])}" + ("..." if len(names) > 5 else "")
                                            return f"{count} фото"
                                        return str(images) if images else ""
                                    except Exception:
                                        return str(value) if value else ""
                                
                                df = df.copy()
                                df["images_info"] = df["images_json"].apply(_format_images_json)
                                # Можна залишити images_json або видалити - залишаємо для зручності
                        except Exception as brief_err:
                            logger.warning(f"Failed to process briefs table: {brief_err}")

                    if table == "trello_cards":
                        def _json_load(value: Optional[str]) -> List[Dict]:
                            try:
                                data = json.loads(value) if value else []
                                return data if isinstance(data, list) else []
                            except Exception:
                                return []

                        def _format_attachment_links(value: Optional[str]) -> str:
                            items = _json_load(value)
                            links = [item.get("url") for item in items if isinstance(item, dict) and item.get("url")]
                            return "; ".join(links)

                        def _format_checklists(value: Optional[str]) -> str:
                            checklists = _json_load(value)
                            formatted_lists = []
                            for checklist in checklists:
                                name = checklist.get("name") or "Чек-лист"
                                check_items = checklist.get("checkItems", []) if isinstance(checklist, dict) else []
                                total = len(check_items)
                                completed = sum(1 for item in check_items if item.get("state") == "complete")
                                header = f"{name}: Виконано ({completed}/{total})"
                                item_strings = []
                                for item in check_items:
                                    item_name = item.get("name") or "Пункт"
                                    status = "виконано" if item.get("state") == "complete" else "не виконано"
                                    item_strings.append(f"{item_name} ({status})")
                                if item_strings:
                                    formatted_lists.append("; ".join([header] + item_strings))
                                else:
                                    formatted_lists.append(header)
                            return " | ".join(formatted_lists)

                        def _format_comments(value: Optional[str]) -> str:
                            comments = _json_load(value)
                            comment_texts = []
                            for comment in comments:
                                if not isinstance(comment, dict):
                                    continue
                                text = comment.get("text") or ""
                                author = comment.get("author", {})
                                author_name = author.get("fullName") or author.get("username")
                                if author_name and text:
                                    comment_texts.append(f"{author_name}: {text}")
                                elif text:
                                    comment_texts.append(text)
                            return "; ".join(comment_texts)

                        def _format_labels(value: Optional[str]) -> str:
                            labels = _json_load(value)
                            formatted = []
                            for label in labels:
                                if not isinstance(label, dict):
                                    continue
                                name = (label.get("name") or "").strip()
                                color = label.get("color")
                                label_id = label.get("id")
                                parts = [part for part in [name or None, color, label_id] if part]
                                if parts:
                                    formatted.append(" / ".join(parts))
                            return "; ".join(formatted)

                        df = df.copy()
                        if "attachments_json" in df.columns:
                            df["attachments"] = df["attachments_json"].apply(_format_attachment_links)
                        if "media_files_json" in df.columns:
                            df["media_files"] = df["media_files_json"].apply(_format_attachment_links)
                        if "checklists_json" in df.columns:
                            df["checklists"] = df["checklists_json"].apply(_format_checklists)
                        if "comments_json" in df.columns:
                            df["comments"] = df["comments_json"].apply(_format_comments)
                        if "labels_json" in df.columns:
                            df["labels"] = df["labels_json"].apply(_format_labels)

                        df = df.drop(
                            columns=["attachments_json", "media_files_json", "checklists_json", "comments_json", "labels_json"],
                            errors="ignore",
                        )

                    self._format_datetime_columns(df, datetime_columns_map.get(table, []))
                    self._format_date_columns(df, date_columns_map.get(table, []))

                    sheet_name = table[:31] or "Sheet1"
                    df.to_excel(writer, sheet_name=sheet_name, index=False)

            # Повертаємо абсолютний шлях для надійності
            abs_output_path = os.path.abspath(output_path)
            logger.info(f"Exported DB tables to {abs_output_path}")
            return abs_output_path
        except PermissionError as perm_err:
            error_msg = (
                f"Не вдалося експортувати Excel файл: файл відкритий в іншій програмі.\n"
                f"  Закрийте файл '{output_path}' в Excel або іншій програмі та спробуйте знову."
            )
            logger.error(error_msg)
            print(f"\n   {error_msg}")
            return None
        except OSError as os_err:
            if os_err.errno == 13:  # Permission denied
                error_msg = (
                    f"Не вдалося експортувати Excel файл: файл відкритий в іншій програмі.\n"
                    f"  Закрийте файл '{output_path}' в Excel або іншій програмі та спробуйте знову."
                )
                logger.error(error_msg)
                print(f"\n   {error_msg}")
                return None
            else:
                logger.error(f"Failed to export tables to Excel: {os_err}")
                return None
        except Exception as e:
            logger.error(f"Failed to export tables to Excel: {e}")
            return None
        finally:
            conn.close()
