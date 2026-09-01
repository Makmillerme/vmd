#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для перегенерації Excel файлу з бази даних
"""

import asyncio
import sys
import os
import codecs
from pathlib import Path
from datetime import datetime

# Виправлення для Windows консолі
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Додаємо корінь проекту до шляху
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.core.exporter import ExcelExporter
from vmd_extractor.config import DB_PATH, EXTRACT_DATA_DIR


async def regenerate_excel():
    """Перегенерує Excel файл з бази даних"""
    print("=" * 80)
    print("ПЕРЕГЕНЕРАЦІЯ EXCEL ФАЙЛУ")
    print("=" * 80)
    print()
    
    # Ініціалізуємо БД
    db = VMDDatabase(DB_PATH)
    await db.initialize()
    
    print(f"📁 База даних: {DB_PATH}")
    print(f"📁 Папка експорту: {EXTRACT_DATA_DIR}")
    print()
    
    # Створюємо експортер
    exporter = ExcelExporter(database=db)
    
    # Використовуємо фіксоване ім'я основного файлу
    filename = "vmd_full_export.xlsx"
    
    print(f"📊 Перегенерація Excel файлу: {filename}")
    print()
    
    try:
        # Експортуємо всі таблиці (перезаписуємо існуючий файл)
        output_path = exporter.export_all_tables(filename=filename)
        
        if output_path and os.path.exists(output_path):
            file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
            print("=" * 80)
            print("✅ EXCEL ФАЙЛ УСПІШНО ПЕРЕГЕНЕРОВАНО")
            print("=" * 80)
            print(f"📄 Файл: {os.path.basename(output_path)}")
            print(f"📁 Шлях: {output_path}")
            print(f"📊 Розмір: {file_size:.2f} MB")
            print()
            
            # Перевіряємо вміст
            import pandas as pd
            try:
                xls = pd.ExcelFile(output_path)
                print("📋 Аркуші в файлі:")
                for sheet_name in xls.sheet_names:
                    df = pd.read_excel(output_path, sheet_name=sheet_name)
                    print(f"   - {sheet_name}: {len(df)} рядків")
            except Exception as e:
                print(f"⚠️  Не вдалося перевірити вміст: {e}")
            
            return output_path
        else:
            print("=" * 80)
            print("❌ ПОМИЛКА: Excel файл не створено")
            print("=" * 80)
            return None
            
    except Exception as e:
        print("=" * 80)
        print(f"❌ ПОМИЛКА ПРИ ГЕНЕРАЦІЇ EXCEL: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    result = asyncio.run(regenerate_excel())
    sys.exit(0 if result else 1)

