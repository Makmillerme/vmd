#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Конвертер фото брифів в PDF
"""

import os
import logging
from typing import List, Optional
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)


class BriefPDFConverter:
    """Конвертер фото в PDF"""
    
    def __init__(self):
        pass
    
    def convert_images_to_pdf(self, image_paths: List[str], output_pdf_path: str) -> bool:
        """
        Конвертує список фото в один PDF файл
        
        Args:
            image_paths: Список шляхів до фото
            output_pdf_path: Шлях до вихідного PDF файлу
        
        Returns:
            True якщо успішно, False інакше
        """
        if not image_paths:
            logger.warning("No images to convert")
            return False
        
        try:
            # Відкриваємо всі зображення
            images = []
            for img_path in image_paths:
                if not os.path.exists(img_path):
                    logger.warning(f"Image not found: {img_path}")
                    continue
                
                try:
                    img = Image.open(img_path)
                    # Конвертуємо в RGB якщо потрібно (для PNG з прозорістю)
                    if img.mode in ('RGBA', 'LA', 'P'):
                        # Створюємо білий фон
                        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                        img = rgb_img
                    elif img.mode != 'RGB':
                        img = img.convert('RGB')
                    
                    images.append(img)
                except Exception as e:
                    logger.error(f"Error opening image {img_path}: {e}")
                    continue
            
            if not images:
                logger.error("No valid images to convert")
                return False
            
            # Створюємо PDF
            # Використовуємо перше зображення як основу
            if len(images) == 1:
                images[0].save(output_pdf_path, 'PDF', resolution=100.0)
            else:
                # Зберігаємо всі зображення в один PDF
                images[0].save(
                    output_pdf_path,
                    'PDF',
                    resolution=100.0,
                    save_all=True,
                    append_images=images[1:]
                )
            
            logger.info(f"Created PDF: {output_pdf_path} ({len(images)} images)")
            return True
            
        except Exception as e:
            logger.error(f"Error converting images to PDF: {e}", exc_info=True)
            return False
    
    def cleanup_images(self, image_paths: List[str]):
        """Видаляє тимчасові фото файли"""
        for img_path in image_paths:
            try:
                if os.path.exists(img_path):
                    os.remove(img_path)
                    logger.debug(f"Removed temporary image: {img_path}")
            except Exception as e:
                logger.warning(f"Error removing image {img_path}: {e}")



