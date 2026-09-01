#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Оркестратор обробки брифів
"""

import asyncio
import os
import logging
import aiosqlite
from typing import Dict, Optional
from pathlib import Path

from .processor import BriefProcessor
from .parser import BriefParser
from .database import BriefDatabase
from .pdf_converter import BriefPDFConverter
from .downloader import BriefDownloader
from ..config import BRIEF_DIR, BRIEF_IMG_DIR, BRIEF_FILES_DIR, DB_PATH
from ..core.database import VMDDatabase
# ExcelExporter імпортується lazy в методах де потрібен (pandas ~380ms)
from ..utils.helpers import sha256_bytes

logger = logging.getLogger(__name__)


class BriefOrchestrator:
    """Оркестратор обробки брифів"""
    
    def __init__(self, db_path=None):
        if db_path is None:
            db_path = DB_PATH
        self.processor = BriefProcessor()
        self.parser = BriefParser()
        self.database = BriefDatabase(db_path)
        self.vmd_database = VMDDatabase(db_path)  # Для співставлення з авто
        self.pdf_converter = BriefPDFConverter()
        self.downloader = BriefDownloader(brief_database=self.database)
    
    async def process_brief_file(self, imfx_path: str) -> Dict:
        """
        Обробляє один файл брифу
        
        Args:
            imfx_path: Шлях до .imfx файлу
        
        Returns:
            Dict з результатами обробки
        """
        result = {
            'success': False,
            'source_file': os.path.basename(imfx_path),
            'vin': None,
            'pdf_path': None,
            'error': None,
            'skipped': False
        }
        
        try:
            # Крок 0: Перевірка на дублікати
            source_file = os.path.basename(imfx_path)
            
            # Обчислюємо SHA256 хеш файлу
            try:
                with open(imfx_path, 'rb') as f:
                    file_hash = sha256_bytes(f.read())
            except Exception as hash_err:
                logger.warning(f"Failed to compute SHA256 for {source_file}: {hash_err}")
                file_hash = None
            
            # Перевіряємо чи файл вже оброблений
            is_processed = await self.database.is_brief_processed(
                source_file=source_file,
                sha256=file_hash
            )
            
            if is_processed:
                logger.info(f"Brief already processed: {source_file} (skipping)")
                result['skipped'] = True
                result['error'] = "File already processed"
                return result
            
            # Крок 1: Розпакування
            logger.info(f"Extracting {result['source_file']}...")
            extract_result = await self.processor.extract_imfx(imfx_path)
            if not extract_result:
                result['error'] = "Failed to extract imfx file"
                return result
            
            extract_dir = extract_result['extract_dir']
            doclist_path = extract_result['doclist_path']
            
            # Крок 2: Парсинг doclist.xml
            logger.info("Parsing doclist.xml...")
            doclist_info = self.parser.parse_doclist(doclist_path)
            
            if not doclist_info.get('vin_file'):
                result['error'] = "VIN file not found in doclist.xml"
                return result
            
            if not doclist_info.get('photo_file'):
                result['error'] = "Photo file not found in doclist.xml"
                return result
            
            # Крок 3: Витягнення VIN
            vin_file_path = os.path.join(extract_dir, doclist_info['vin_file'])
            if not os.path.exists(vin_file_path):
                result['error'] = f"VIN file not found: {doclist_info['vin_file']}"
                return result
            
            logger.info("Extracting VIN...")
            vin = self.parser.extract_vin(vin_file_path)
            if not vin:
                result['error'] = "VIN not found in XML file"
                return result
            
            result['vin'] = vin
            logger.info(f"Found VIN: {vin}")
            
            # Крок 4: Витягнення фото
            photo_file_path = os.path.join(extract_dir, doclist_info['photo_file'])
            if not os.path.exists(photo_file_path):
                result['error'] = f"Photo file not found: {doclist_info['photo_file']}"
                return result
            
            logger.info("Extracting photos...")
            # Створюємо тимчасову папку для фото
            temp_img_dir = os.path.join(BRIEF_IMG_DIR, f"brief_{result['source_file']}")
            Path(temp_img_dir).mkdir(parents=True, exist_ok=True)
            
            image_paths = self.parser.extract_photos(photo_file_path, temp_img_dir)
            if not image_paths:
                result['error'] = "No photos found in XML file"
                return result
            
            logger.info(f"Extracted {len(image_paths)} photos")
            
            # Крок 5: Конвертація в PDF
            logger.info("Converting photos to PDF...")
            pdf_filename = f"brief_{vin}_{result['source_file']}.pdf"
            pdf_path = os.path.join(BRIEF_DIR, pdf_filename)
            Path(BRIEF_DIR).mkdir(parents=True, exist_ok=True)
            
            success = self.pdf_converter.convert_images_to_pdf(image_paths, pdf_path)
            if not success:
                result['error'] = "Failed to convert images to PDF"
                return result
            
            result['pdf_path'] = pdf_path
            logger.info(f"Created PDF: {pdf_path}")
            
            # Крок 6: Очищення тимчасових фото
            self.pdf_converter.cleanup_images(image_paths)
            
            # Крок 7: Збереження в БД
            logger.info("Saving to database...")
            brief_id = await self.database.save_brief(
                source_file=result['source_file'],
                vin=vin,
                pdf_path=pdf_path,
                images=image_paths,  # Зберігаємо шляхи для історії
                extract_dir=extract_dir,
                sha256=file_hash
            )
            
            if brief_id:
                result['brief_id'] = brief_id
                result['success'] = True
                logger.info(f"Brief saved to DB with ID: {brief_id}")
                
                # Крок 8: Співставлення з авто через VIN
                if vin:
                    await self._link_brief_to_vehicle(vin, pdf_path)
            else:
                result['error'] = "Failed to save to database"
            
        except Exception as e:
            logger.error(f"Error processing brief: {e}", exc_info=True)
            result['error'] = str(e)
        
        return result
    
    async def _link_brief_to_vehicle(self, vin: str, brief_pdf_path: str):
        """
        Співставляє бриф з авто через VIN код
        
        Args:
            vin: VIN код
            brief_pdf_path: Шлях до PDF файлу брифу
        """
        try:
            # Нормалізуємо VIN
            vin_normalized = vin.strip().upper()
            if not vin_normalized:
                return
            
            # Шукаємо авто за VIN
            vehicles = await self.vmd_database.get_vehicles_by_vins([vin_normalized])
            
            if vehicles:
                # Знайдено авто - оновлюємо з шляхом до брифу
                await self.vmd_database.initialize()
                async with aiosqlite.connect(self.vmd_database.db_path) as db:
                    for vehicle in vehicles:
                        vehicle_id = vehicle.get('id')
                        if vehicle_id:
                            await db.execute(
                                "UPDATE vehicles SET brief_pdf_path = ? WHERE id = ?",
                                (brief_pdf_path, vehicle_id)
                            )
                            logger.info(f"Linked brief to vehicle ID {vehicle_id} (VIN: {vin_normalized})")
                    await db.commit()
            else:
                logger.debug(f"No vehicle found for VIN: {vin_normalized}")
                
        except Exception as e:
            logger.warning(f"Error linking brief to vehicle: {e}", exc_info=True)
    
    async def process_local_files(self, files_dir: str = None) -> Dict:
        """
        Обробляє всі .imfx файли з локальної папки
        
        Args:
            files_dir: Папка з файлами (за замовчуванням BRIEF_FILES_DIR)
        
        Returns:
            Dict з результатами обробки
        """
        if files_dir is None:
            files_dir = str(BRIEF_FILES_DIR)
        
        results = {
            'found': 0,
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'errors': []
        }
        
        try:
            # Знаходимо всі .imfx файли
            files = []
            for file_path in Path(files_dir).glob("*.imfx"):
                files.append(str(file_path))
            
            if not files:
                logger.info(f"No .imfx files found in {files_dir}")
                return results
            
            results['found'] = len(files)
            logger.info(f"Found {len(files)} files to process")
            
            # Обробляємо кожен файл
            for file_path in files:
                file_name = os.path.basename(file_path)
                
                try:
                    logger.info(f"Processing file: {file_name}")
                    result = await self.process_brief_file(file_path)
                    
                    results['processed'] += 1
                    
                    if result.get('skipped'):
                        logger.info(f"Skipped (already processed): {file_name}")
                        continue
                    
                    if result['success']:
                        results['successful'] += 1
                        logger.info(f"Successfully processed: {file_name} (VIN: {result.get('vin')})")
                    else:
                        results['failed'] += 1
                        error_msg = f"{file_name}: {result.get('error', 'Unknown error')}"
                        results['errors'].append(error_msg)
                        logger.error(error_msg)
                    
                except Exception as e:
                    results['failed'] += 1
                    error_msg = f"{file_name}: {str(e)}"
                    results['errors'].append(error_msg)
                    logger.error(f"Error processing {file_name}: {e}", exc_info=True)
            
            logger.info(f"Processing complete: {results['successful']} successful, {results['failed']} failed")
            
            # Експорт Excel після обробки (якщо були успішні обробки)
            if results['successful'] > 0:
                logger.info("Exporting to Excel...")
                try:
                    from ..core.exporter import ExcelExporter  # Lazy import
                    exporter = ExcelExporter(database=self.vmd_database)
                    excel_path = exporter.export_all_tables()
                    if excel_path:
                        logger.info(f"Excel exported: {excel_path}")
                        results['excel_path'] = excel_path
                    else:
                        logger.warning("Excel export failed")
                except Exception as excel_err:
                    logger.warning(f"Error exporting Excel: {excel_err}")
                    results['errors'].append(f"Excel export error: {str(excel_err)}")
            
        except Exception as e:
            logger.error(f"Error in process_local_files: {e}", exc_info=True)
            results['errors'].append(f"Fatal error: {str(e)}")
        
        return results
    
    async def link_all_briefs_to_vehicles(self) -> Dict:
        """
        Співставляє всі брифі з авто через VIN коди
        
        Returns:
            Dict з результатами співставлення
        """
        results = {
            'briefs_found': 0,
            'vehicles_found': 0,
            'linked': 0,
            'not_found': 0,
            'errors': []
        }
        
        try:
            # Отримуємо всі брифі з VIN
            briefs = await self.database.get_all_briefs(limit=10000)
            briefs_with_vin = [b for b in briefs if b.get('vin')]
            
            if not briefs_with_vin:
                logger.info("No briefs with VIN found")
                return results
            
            results['briefs_found'] = len(briefs_with_vin)
            logger.info(f"Found {len(briefs_with_vin)} briefs with VIN")
            
            # Групуємо по VIN для ефективного пошуку
            vins = [b['vin'].strip().upper() for b in briefs_with_vin if b.get('vin')]
            unique_vins = list(set(vins))
            
            # Шукаємо авто за всіма VIN одночасно
            vehicles = await self.vmd_database.get_vehicles_by_vins(unique_vins)
            results['vehicles_found'] = len(vehicles)
            
            # Створюємо мапу VIN -> vehicle_id
            vin_to_vehicle = {}
            for vehicle in vehicles:
                vin = (vehicle.get('vin') or '').strip().upper()
                if vin:
                    vin_to_vehicle[vin] = vehicle.get('id')
            
            # Оновлюємо vehicles з brief_pdf_path
            await self.vmd_database.initialize()
            async with aiosqlite.connect(self.vmd_database.db_path) as db:
                for brief in briefs_with_vin:
                    vin = (brief.get('vin') or '').strip().upper()
                    pdf_path = brief.get('pdf_path')
                    
                    if not vin or not pdf_path:
                        continue
                    
                    vehicle_id = vin_to_vehicle.get(vin)
                    if vehicle_id:
                        try:
                            await db.execute(
                                "UPDATE vehicles SET brief_pdf_path = ? WHERE id = ?",
                                (pdf_path, vehicle_id)
                            )
                            results['linked'] += 1
                            logger.debug(f"Linked brief {brief.get('source_file')} to vehicle ID {vehicle_id}")
                        except Exception as e:
                            error_msg = f"Error linking brief {brief.get('source_file')}: {e}"
                            results['errors'].append(error_msg)
                            logger.error(error_msg)
                    else:
                        results['not_found'] += 1
                        logger.debug(f"No vehicle found for VIN: {vin} (brief: {brief.get('source_file')})")
                
                await db.commit()
            
            logger.info(f"Linked {results['linked']} briefs to vehicles, {results['not_found']} not found")
            
            # Експорт Excel після співставлення (якщо були співставлення)
            if results['linked'] > 0:
                logger.info("Exporting to Excel after linking...")
                try:
                    from ..core.exporter import ExcelExporter  # Lazy import
                    exporter = ExcelExporter(database=self.vmd_database)
                    excel_path = exporter.export_all_tables()
                    if excel_path:
                        logger.info(f"Excel exported: {excel_path}")
                        results['excel_path'] = excel_path
                    else:
                        logger.warning("Excel export failed")
                except Exception as excel_err:
                    logger.warning(f"Error exporting Excel: {excel_err}")
                    results['errors'].append(f"Excel export error: {str(excel_err)}")
            
        except Exception as e:
            logger.error(f"Error in link_all_briefs_to_vehicles: {e}", exc_info=True)
            results['errors'].append(f"Fatal error: {str(e)}")
        
        return results
    
    async def process_files_from_google_drive(
        self,
        use_api: bool = False,
        status_filter: Optional[str] = "PENDING",
        cleanup_after: bool = True
    ) -> Dict:
        """
        Завантажує файли з Google Drive та обробляє їх
        
        Args:
            use_api: Якщо True - використовує API (з оновленням статусу), якщо False - пряме завантаження
            status_filter: Фільтр по статусу ('PENDING', 'DOWNLOADED', 'PROCESSED') - тільки для API
            cleanup_after: Видаляти завантажені файли після обробки
        
        Returns:
            Dict з результатами обробки
        """
        results = {
            'downloaded': 0,
            'processed': 0,
            'successful': 0,
            'failed': 0,
            'errors': []
        }
        
        try:
            # Крок 1: Завантаження з Google Drive (з перевіркою дублікатів)
            logger.info("Downloading files from Google Drive (with duplicate check)...")
            downloaded_files = await self.downloader.download_from_google_drive(
                file_extensions=['.imfx'],
                use_api=use_api,
                status_filter=status_filter,
                max_concurrent=5,  # Паралельне завантаження до 5 файлів одночасно
                skip_duplicates=True  # Пропускати дублікати
            )
            
            if not downloaded_files:
                logger.warning("No files downloaded from Google Drive")
                return results
            
            results['downloaded'] = len(downloaded_files)
            logger.info(f"Downloaded {len(downloaded_files)} files")
            
            # Крок 2: Обробка кожного файлу
            for file_info in downloaded_files:
                file_path = file_info['local_path']
                file_name = file_info['filename']
                
                try:
                    logger.info(f"Processing file: {file_name}")
                    result = await self.process_brief_file(file_path)
                    
                    results['processed'] += 1
                    
                    if result.get('skipped'):
                        logger.info(f"Skipped (already processed): {file_name}")
                        continue
                    
                    if result['success']:
                        results['successful'] += 1
                        logger.info(f"Successfully processed: {file_name} (VIN: {result.get('vin')})")
                    else:
                        results['failed'] += 1
                        error_msg = f"{file_name}: {result.get('error', 'Unknown error')}"
                        results['errors'].append(error_msg)
                        logger.error(error_msg)
                    
                    # Видаляємо завантажений файл якщо потрібно
                    if cleanup_after:
                        try:
                            os.remove(file_path)
                            logger.debug(f"Removed downloaded file: {file_path}")
                        except Exception as e:
                            logger.warning(f"Error removing file {file_path}: {e}")
                    
                except Exception as e:
                    results['failed'] += 1
                    error_msg = f"{file_name}: {str(e)}"
                    results['errors'].append(error_msg)
                    logger.error(f"Error processing {file_name}: {e}", exc_info=True)
            
            logger.info(f"Processing complete: {results['successful']} successful, {results['failed']} failed")
            
            # Експорт Excel після обробки (якщо були успішні обробки)
            if results['successful'] > 0:
                logger.info("Exporting to Excel...")
                try:
                    from ..core.exporter import ExcelExporter  # Lazy import
                    exporter = ExcelExporter(database=self.vmd_database)
                    excel_path = exporter.export_all_tables()
                    if excel_path:
                        logger.info(f"Excel exported: {excel_path}")
                        results['excel_path'] = excel_path
                    else:
                        logger.warning("Excel export failed")
                except Exception as excel_err:
                    logger.warning(f"Error exporting Excel: {excel_err}")
                    results['errors'].append(f"Excel export error: {str(excel_err)}")
            
        except Exception as e:
            logger.error(f"Error in process_files_from_google_drive: {e}", exc_info=True)
            results['errors'].append(f"Fatal error: {str(e)}")
        
        return results

