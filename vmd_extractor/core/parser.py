#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Асинхронний парсер ВМД даних
"""

import asyncio
import os
import logging
from typing import List, Dict, Optional

from ..utils.xml_parser import parse_doc2

logger = logging.getLogger(__name__)


class AsyncVMDParser:
    """Асинхронний парсер ВМД даних"""
    
    async def parse_document(self, doc2_path: str, source_file: str) -> List[Dict]:
        """Асинхронний парсинг одного документа"""
        try:
            # Перевіряємо чи існує файл
            if not os.path.exists(doc2_path):
                logger.error(f"Файл doc2.xml не знайдено: {doc2_path}")
                return []
            
            loop = asyncio.get_event_loop()
            
            # Виконуємо парсинг в executor (I/O операція)
            rows = await loop.run_in_executor(
                None, parse_doc2, doc2_path, source_file
            )
            
            # Перевіряємо результати
            if not rows:
                logger.warning(f"Дані не знайдено в {source_file}")
                return []
            
            # Перевіряємо чи є помилки
            errors = [row for row in rows if "error" in row]
            if errors:
                logger.error(f"Parse errors in {source_file}: {errors[0].get('error', 'Unknown error')}")
                return []
            
            # Детальне логування кожного розпарсеного транспортного засобу
            for row in rows:
                brand = row.get("brand", "").strip() or "не вказано"
                model = row.get("model", "").strip() or "не вказано"
                vin = row.get("vin", "").strip() or "не вказано"
                vehicle_type = row.get("vehicle_type", "").strip() or "не вказано"
                year = row.get("year_calendar") or row.get("year_model") or "не вказано"
                
                print(f"   {brand} {model} | VIN: {vin} | Тип: {vehicle_type} | Рік: {year}")
            
            # Логування тільки для debug
            logger.debug(f"Parsed {len(rows)} records from {source_file}")
            return rows
                
        except Exception as e:
            logger.error(f"Помилка парсингу {doc2_path}: {e}", exc_info=True)
            return []
    
    async def parse_documents(self, processed_files: List[Dict], show_progress: bool = False) -> List[Dict]:
        """Асинхронний парсинг списку документів"""
        total = len(processed_files)
        parsed_count = 0
        all_rows = []
        
        # Створюємо завдання для паралельного парсингу
        tasks = [
            self.parse_document(file_info["doc2_path"], file_info["source_file"])
            for file_info in processed_files
        ]
        
        # Виконуємо парсинг паралельно з відстеженням прогресу
        if show_progress:
            for i, coro in enumerate(asyncio.as_completed(tasks)):
                try:
                    result = await coro
                    parsed_count += 1
                    if result:
                        all_rows.extend(result)
                    print(f"   Парсинг: {parsed_count}/{total} ({parsed_count*100//total}%)", end='\r')
                except Exception as e:
                    logger.error(f"Помилка парсингу: {e}")
            print()  # Новий рядок після прогресу
        else:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Помилка парсингу для {processed_files[i]['source_file']}: {result}")
                    continue
                if result:
                    all_rows.extend(result)
        
        return all_rows

