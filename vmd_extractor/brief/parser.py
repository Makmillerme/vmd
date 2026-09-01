#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер брифів - витягнення VIN та фото з XML файлів
"""

import os
import xml.etree.ElementTree as ET
import base64
import logging
from typing import Dict, Optional, List
from pathlib import Path

logger = logging.getLogger(__name__)


class BriefParser:
    """Парсер брифів"""
    
    def __init__(self):
        pass
    
    def parse_doclist(self, doclist_path: str) -> Dict[str, Optional[str]]:
        """
        Парсинг doclist.xml для знаходження файлів з VIN та фото
        
        Returns:
            Dict з ключами: 'vin_file', 'photo_file'
        """
        result = {
            'vin_file': None,
            'photo_file': None
        }
        
        try:
            # Читаємо XML файл
            xml_content = None
            encodings = ['utf-8', 'windows-1251', 'cp1251']
            
            for encoding in encodings:
                try:
                    with open(doclist_path, 'r', encoding=encoding) as f:
                        xml_content = f.read()
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            
            if xml_content is None:
                logger.error(f"Не вдалося прочитати doclist.xml з жодного кодування")
                return result
            
            root = ET.fromstring(xml_content)
            
            # Шукаємо файл з DocCode=2 (VIN)
            for doc in root.iter("Document"):
                doc_code = doc.findtext("DocCode", "")
                if doc_code == "2":
                    filename = doc.findtext("FileName", "")
                    if filename:
                        result['vin_file'] = filename
                        logger.debug(f"Found VIN file: {filename}")
                    break
            
            # Шукаємо файл з Description="2800" (фото)
            for doc in root.iter("Document"):
                description = doc.findtext("Description", "")
                if description == "2800":
                    filename = doc.findtext("FileName", "")
                    if filename:
                        result['photo_file'] = filename
                        logger.debug(f"Found photo file: {filename}")
                    break
            
        except Exception as e:
            logger.error(f"Error parsing doclist.xml: {e}", exc_info=True)
        
        return result
    
    def extract_vin(self, xml_path: str) -> Optional[str]:
        """
        Витягнення VIN коду з XML файлу
        
        Шукає в ccd_inv_det з ccd_id_code 82, 84 або 98
        """
        try:
            # Читаємо XML файл
            xml_content = None
            encodings = ['utf-8', 'windows-1251', 'cp1251']
            
            for encoding in encodings:
                try:
                    with open(xml_path, 'r', encoding=encoding) as f:
                        xml_content = f.read()
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            
            if xml_content is None:
                logger.error(f"Не вдалося прочитати XML файл з жодного кодування")
                return None
            
            root = ET.fromstring(xml_content)
            
            # Шукаємо VIN в ccd_inv_det з кодом 82, 84 або 98
            vin_codes = ['82', '84', '98']
            
            for inv_det in root.iter("ccd_inv_det"):
                id_code = inv_det.findtext("ccd_id_code", "")
                if id_code in vin_codes:
                    vin = inv_det.findtext("ccd_id_value", "").strip()
                    if vin:
                        logger.debug(f"Found VIN: {vin} (code: {id_code})")
                        return vin
            
            logger.warning(f"VIN not found in {xml_path}")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting VIN from {xml_path}: {e}", exc_info=True)
            return None
    
    def extract_photos(self, xml_path: str, output_dir: str) -> List[str]:
        """
        Витягнення фото з base64 з XML файлу та збереження в output_dir
        
        Returns:
            List шляхів до збережених фото файлів
        """
        saved_images = []
        
        try:
            # Читаємо XML файл
            xml_content = None
            encodings = ['utf-8', 'windows-1251', 'cp1251']
            
            for encoding in encodings:
                try:
                    with open(xml_path, 'r', encoding=encoding) as f:
                        xml_content = f.read()
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            
            if xml_content is None:
                logger.error(f"Не вдалося прочитати XML файл з жодного кодування")
                return saved_images
            
            root = ET.fromstring(xml_content)
            
            # Створюємо папку для фото якщо не існує
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            
            # Шукаємо всі base64 закодовані зображення
            # Зазвичай вони знаходяться в елементах типу <Image>, <Photo>, <Picture>, <Binary> або просто текстових полях
            image_count = 0
            
            # Список можливих назв елементів для зображень
            image_element_names = ['Image', 'Photo', 'Picture', 'Binary', 'BinaryData', 'ImageData', 'PhotoData']
            
            # Спочатку шукаємо в специфічних елементах
            for elem_name in image_element_names:
                for elem in root.iter(elem_name):
                    text = (elem.text or "").strip()
                    if text and len(text) > 100:
                        image_data = self._try_decode_base64_image(text)
                        if image_data:
                            image_count += 1
                            ext = self._detect_image_format(image_data)
                            if ext:
                                image_path = os.path.join(output_dir, f"photo_{image_count}{ext}")
                                with open(image_path, 'wb') as f:
                                    f.write(image_data)
                                saved_images.append(image_path)
                                logger.debug(f"Saved photo {image_count} from {elem_name}: {image_path}")
            
            # Шукаємо в текстових полях всіх елементів
            for elem in root.iter():
                text = (elem.text or "").strip()
                if not text or len(text) < 100:
                    continue
                
                # Пропускаємо якщо це вже оброблений елемент зображення
                if elem.tag in image_element_names:
                    continue
                
                image_data = self._try_decode_base64_image(text)
                if image_data:
                    image_count += 1
                    ext = self._detect_image_format(image_data)
                    if ext:
                        image_path = os.path.join(output_dir, f"photo_{image_count}{ext}")
                        with open(image_path, 'wb') as f:
                            f.write(image_data)
                        saved_images.append(image_path)
                        logger.debug(f"Saved photo {image_count} from {elem.tag}: {image_path}")
            
            # Також шукаємо в атрибутах
            for elem in root.iter():
                for attr_name, attr_value in elem.attrib.items():
                    if not attr_value or len(attr_value) < 100:
                        continue
                    
                    image_data = self._try_decode_base64_image(attr_value)
                    if image_data:
                        image_count += 1
                        ext = self._detect_image_format(image_data)
                        if ext:
                            image_path = os.path.join(output_dir, f"photo_{image_count}{ext}")
                            with open(image_path, 'wb') as f:
                                f.write(image_data)
                            saved_images.append(image_path)
                            logger.debug(f"Saved photo {image_count} from attribute {attr_name}: {image_path}")
            
            if not saved_images:
                logger.warning(f"No photos found in {xml_path}")
            
        except Exception as e:
            logger.error(f"Error extracting photos from {xml_path}: {e}", exc_info=True)
        
        return saved_images
    
    def _try_decode_base64_image(self, text: str) -> Optional[bytes]:
        """Спробує декодувати base64 та перевірити чи це зображення"""
        try:
            image_data = base64.b64decode(text)
            # Перевіряємо чи це дійсно зображення (перевірка заголовків)
            if len(image_data) < 10:
                return None
            
            # JPEG: FF D8 FF
            if image_data[:3] == b'\xff\xd8\xff':
                return image_data
            # PNG: 89 50 4E 47
            if image_data[:4] == b'\x89PNG':
                return image_data
            # BMP: 42 4D
            if image_data[:2] == b'BM':
                return image_data
            # GIF: 47 49 46 38
            if image_data[:4] == b'GIF8':
                return image_data
            
            return None
        except Exception:
            return None
    
    def _detect_image_format(self, image_data: bytes) -> Optional[str]:
        """Визначає формат зображення"""
        if len(image_data) < 4:
            return None
        
        if image_data[:3] == b'\xff\xd8\xff':
            return '.jpg'
        if image_data[:4] == b'\x89PNG':
            return '.png'
        if image_data[:2] == b'BM':
            return '.bmp'
        if image_data[:4] == b'GIF8':
            return '.gif'
        
        return None

