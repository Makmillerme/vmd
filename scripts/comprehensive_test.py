#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Комплексний тест перевірки роботоспроможності системи VMD Extractor
"""

import sys
import asyncio
import codecs
from pathlib import Path
from datetime import datetime

# Налаштування UTF-8 для Windows
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Додаємо корінь проекту до шляху
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Результати тестів
test_results = {
    "passed": 0,
    "failed": 0,
    "warnings": 0,
    "errors": []
}


def print_header(text):
    """Виводить заголовок"""
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80)


def print_test(name, status, message=""):
    """Виводить результат тесту"""
    status_symbol = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    print(f"  {status_symbol} {name}")
    if message:
        print(f"     {message}")
    
    if status == "PASS":
        test_results["passed"] += 1
    elif status == "FAIL":
        test_results["failed"] += 1
        test_results["errors"].append(f"{name}: {message}")
    elif status == "WARN":
        test_results["warnings"] += 1


def test_imports():
    """Тест 1: Перевірка імпортів"""
    print_header("ТЕСТ 1: ПЕРЕВІРКА ІМПОРТІВ")
    
    modules_to_test = [
        ("vmd_extractor.core.database", "VMDDatabase"),
        ("vmd_extractor.core.exporter", "ExcelExporter"),
        ("vmd_extractor.core.orchestrator", "VMDOrchestrator"),
        ("vmd_extractor.utils.trello_integration", "TrelloIntegration"),
        ("vmd_extractor.utils.xml_parser", "parse_doc2"),
        ("vmd_extractor.cli.menus.base", "BaseMenu"),
        ("vmd_extractor.cli.menus.trello.base", "BaseTrelloMenu"),
        ("vmd_extractor.cli.menus.trello.menu", "TrelloMenu"),
        ("vmd_extractor.cli.menus.trello.sync", "sync_vehicles_to_trello"),
        ("vmd_extractor.cli.menus.trello.cards", "show_trello_stats"),
        ("vmd_extractor.cli.menus.trello.labels", "show_trello_labels_menu"),
        ("vmd_extractor.cli.menus.trello.custom_fields", "sync_custom_fields_for_all_cards"),
    ]
    
    for module_path, item_name in modules_to_test:
        try:
            module = __import__(module_path, fromlist=[item_name])
            getattr(module, item_name)
            print_test(f"Імпорт {module_path}.{item_name}", "PASS")
        except ImportError as e:
            print_test(f"Імпорт {module_path}.{item_name}", "FAIL", f"ImportError: {e}")
        except AttributeError as e:
            print_test(f"Імпорт {module_path}.{item_name}", "FAIL", f"AttributeError: {e}")
        except Exception as e:
            print_test(f"Імпорт {module_path}.{item_name}", "FAIL", f"Помилка: {e}")


async def test_database():
    """Тест 2: Перевірка бази даних"""
    print_header("ТЕСТ 2: ПЕРЕВІРКА БАЗИ ДАНИХ")
    
    try:
        from vmd_extractor.core.database import VMDDatabase
        from vmd_extractor.config import DB_PATH
        
        # Перевірка існування файлу БД
        if not Path(DB_PATH).exists():
            print_test("Файл БД існує", "WARN", f"Файл {DB_PATH} не знайдено")
        else:
            print_test("Файл БД існує", "PASS")
        
        # Перевірка підключення до БД
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        print_test("Підключення до БД", "PASS")
        
        # Перевірка структури таблиць
        required_tables = [
            "vehicles", "processed_files", "email_messages",
            "sync_runs", "trello_cards", "trello_labels", "briefs"
        ]
        
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            existing_tables = {row[0] for row in await cursor.fetchall()}
        
        for table in required_tables:
            if table in existing_tables:
                print_test(f"Таблиця {table} існує", "PASS")
            else:
                print_test(f"Таблиця {table} існує", "FAIL", "Таблиця не знайдена")
        
        # Перевірка колонок vehicles
        required_columns = [
            "id", "vin", "brand", "model", "vehicle_type",
            "serial_number", "year_calendar", "payload_json"
        ]
        
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute("PRAGMA table_info(vehicles)")
            existing_columns = {row[1] for row in await cursor.fetchall()}
        
        for column in required_columns:
            if column in existing_columns:
                print_test(f"Колонка vehicles.{column} існує", "PASS")
            else:
                print_test(f"Колонка vehicles.{column} існує", "FAIL", "Колонка не знайдена")
        
        # Перевірка статистики
        try:
            summary = await db.get_trello_summary()
            print_test("Метод get_trello_summary()", "PASS", f"Знайдено {summary.get('total_valid_vehicles', 0)} vehicles")
        except Exception as e:
            print_test("Метод get_trello_summary()", "FAIL", f"Помилка: {e}")
        
    except Exception as e:
        print_test("Підключення до БД", "FAIL", f"Помилка: {e}")


async def test_trello_modules():
    """Тест 3: Перевірка Trello модулів"""
    print_header("ТЕСТ 3: ПЕРЕВІРКА TRELLO МОДУЛІВ")
    
    # Перевірка наявності функцій
    trello_functions = {
        "sync": [
            "sync_vehicles_to_trello",
            "_sync_card_data_to_db",
            "_sync_all_existing_cards_from_trello",
            "_cleanup_trello_cards"
        ],
        "cards": [
            "show_trello_stats",
            "verify_trello_links",
            "add_trello_cards_by_vins"
        ],
        "labels": [
            "show_trello_labels_menu",
            "create_trello_labels",
            "show_trello_labels_list",
            "check_vehicle_type_duplicates",
            "fix_vehicle_type_case",
            "fix_vehicle_type_typos_in_db",
            "update_label_colors_to_sky",
            "remove_all_labels_from_cards",
            "sync_labels_on_all_cards"
        ],
        "custom_fields": [
            "sync_custom_fields_for_all_cards",
            "check_and_fix_custom_fields_for_all_cards"
        ]
    }
    
    for module_name, functions in trello_functions.items():
        try:
            module = __import__(f"vmd_extractor.cli.menus.trello.{module_name}", fromlist=functions)
            for func_name in functions:
                if hasattr(module, func_name):
                    print_test(f"trello.{module_name}.{func_name}", "PASS")
                else:
                    print_test(f"trello.{module_name}.{func_name}", "FAIL", "Функція не знайдена")
        except Exception as e:
            print_test(f"Модуль trello.{module_name}", "FAIL", f"Помилка: {e}")
    
    # Перевірка TrelloMenu
    try:
        from vmd_extractor.cli.menus.trello.menu import TrelloMenu, show_trello_menu
        print_test("TrelloMenu клас", "PASS")
        print_test("show_trello_menu() функція", "PASS")
    except Exception as e:
        print_test("TrelloMenu клас", "FAIL", f"Помилка: {e}")


async def test_excel_export():
    """Тест 4: Перевірка Excel експорту"""
    print_header("ТЕСТ 4: ПЕРЕВІРКА EXCEL ЕКСПОРТУ")
    
    try:
        from vmd_extractor.core.exporter import ExcelExporter
        from vmd_extractor.core.database import VMDDatabase
        from vmd_extractor.config import DB_PATH
        
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        exporter = ExcelExporter(database=db)
        print_test("ExcelExporter ініціалізація", "PASS")
        
        # Перевірка методу export_all_tables
        try:
            excel_path = exporter.export_all_tables()
            if excel_path and Path(excel_path).exists():
                print_test("Метод export_all_tables()", "PASS", f"Файл: {excel_path}")
                
                # Перевірка розміру файлу
                file_size = Path(excel_path).stat().st_size
                if file_size > 0:
                    print_test("Розмір Excel файлу", "PASS", f"{file_size} байт")
                else:
                    print_test("Розмір Excel файлу", "WARN", "Файл порожній")
            else:
                print_test("Метод export_all_tables()", "FAIL", "Файл не створено")
        except Exception as e:
            print_test("Метод export_all_tables()", "FAIL", f"Помилка: {e}")
        
    except Exception as e:
        print_test("ExcelExporter", "FAIL", f"Помилка: {e}")


async def test_cli_modules():
    """Тест 5: Перевірка CLI модулів"""
    print_header("ТЕСТ 5: ПЕРЕВІРКА CLI МОДУЛІВ")
    
    cli_modules = [
        ("vmd_extractor.cli.menus.main", "MainMenu"),
        ("vmd_extractor.cli.menus.database", "DatabaseMenu"),
        ("vmd_extractor.cli.menus.download", "DownloaderMenu"),
        ("vmd_extractor.cli.menus.report", "ReportMenu"),
        ("vmd_extractor.cli.menus.mailing", "MailingMenu"),
        ("vmd_extractor.cli.menus.trello.menu", "TrelloMenu"),
    ]
    
    for module_path, class_name in cli_modules:
        try:
            module = __import__(module_path, fromlist=[class_name])
            menu_class = getattr(module, class_name)
            
            # Перевірка базового класу
            from vmd_extractor.cli.menus.base import BaseMenu
            if issubclass(menu_class, BaseMenu):
                print_test(f"CLI модуль {class_name}", "PASS", "Наслідує BaseMenu")
            else:
                print_test(f"CLI модуль {class_name}", "WARN", "Не наслідує BaseMenu")
        except Exception as e:
            print_test(f"CLI модуль {class_name}", "FAIL", f"Помилка: {e}")


async def test_config():
    """Тест 6: Перевірка конфігурації"""
    print_header("ТЕСТ 6: ПЕРЕВІРКА КОНФІГУРАЦІЇ")
    
    try:
        from vmd_extractor.config import (
            DB_PATH, PDF_DIR, TRELLO_ENABLED,
            TRELLO_API_KEY, TRELLO_API_TOKEN, TRELLO_BOARD_ID, TRELLO_LIST_ID
        )
        
        # Перевірка шляхів
        if DB_PATH:
            print_test("DB_PATH налаштовано", "PASS", f"Шлях: {DB_PATH}")
        else:
            print_test("DB_PATH налаштовано", "FAIL", "Не налаштовано")
        
        if PDF_DIR:
            print_test("PDF_DIR налаштовано", "PASS", f"Шлях: {PDF_DIR}")
        else:
            print_test("PDF_DIR налаштовано", "WARN", "Не налаштовано")
        
        # Перевірка Trello налаштувань
        if TRELLO_ENABLED:
            print_test("TRELLO_ENABLED", "PASS", "Увімкнено")
            
            if TRELLO_API_KEY and TRELLO_API_TOKEN:
                print_test("Trello API credentials", "PASS", "Налаштовано")
            else:
                print_test("Trello API credentials", "WARN", "Не налаштовано")
            
            if TRELLO_BOARD_ID and TRELLO_LIST_ID:
                print_test("Trello Board/List ID", "PASS", "Налаштовано")
            else:
                print_test("Trello Board/List ID", "WARN", "Не налаштовано")
        else:
            print_test("TRELLO_ENABLED", "WARN", "Вимкнено")
        
    except Exception as e:
        print_test("Конфігурація", "FAIL", f"Помилка: {e}")


async def test_data_integrity():
    """Тест 7: Перевірка цілісності даних"""
    print_header("ТЕСТ 7: ПЕРЕВІРКА ЦІЛІСНОСТІ ДАНИХ")
    
    try:
        from vmd_extractor.core.database import VMDDatabase
        from vmd_extractor.config import DB_PATH
        
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        # Перевірка vehicles
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM vehicles")
            vehicles_count = (await cursor.fetchone())[0]
            print_test("Кількість vehicles", "PASS", f"Знайдено: {vehicles_count}")
            
            # Перевірка наявності нормалізованих колонок
            cursor = await conn.execute("""
                SELECT COUNT(*) FROM vehicles 
                WHERE vin IS NOT NULL AND vin != ''
            """)
            vehicles_with_vin = (await cursor.fetchone())[0]
            print_test("Vehicles з VIN", "PASS", f"Знайдено: {vehicles_with_vin}")
            
            cursor = await conn.execute("""
                SELECT COUNT(*) FROM vehicles 
                WHERE vehicle_type IS NOT NULL AND vehicle_type != ''
            """)
            vehicles_with_type = (await cursor.fetchone())[0]
            print_test("Vehicles з типом", "PASS", f"Знайдено: {vehicles_with_type}")
        
        # Перевірка trello_cards
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM trello_cards")
            cards_count = (await cursor.fetchone())[0]
            print_test("Кількість trello_cards", "PASS", f"Знайдено: {cards_count}")
        
        # Перевірка trello_labels
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM trello_labels")
            labels_count = (await cursor.fetchone())[0]
            print_test("Кількість trello_labels", "PASS", f"Знайдено: {labels_count}")
        
    except Exception as e:
        print_test("Цілісність даних", "FAIL", f"Помилка: {e}")


async def test_utils():
    """Тест 8: Перевірка утиліт"""
    print_header("ТЕСТ 8: ПЕРЕВІРКА УТИЛІТ")
    
    # Перевірка xml_parser
    try:
        from vmd_extractor.utils.xml_parser import parse_doc2
        print_test("xml_parser.parse_doc2", "PASS")
    except Exception as e:
        print_test("xml_parser.parse_doc2", "FAIL", f"Помилка: {e}")
    
    # Перевірка trello_integration
    try:
        from vmd_extractor.utils.trello_integration import TrelloIntegration
        print_test("trello_integration.TrelloIntegration", "PASS")
    except Exception as e:
        print_test("trello_integration.TrelloIntegration", "FAIL", f"Помилка: {e}")
    
    # Перевірка helpers
    try:
        from vmd_extractor.utils.helpers import normalize_vehicle_type
        print_test("helpers.normalize_vehicle_type", "PASS")
        
        # Тест функції
        test_type = "автомобіль вантажний"
        normalized = normalize_vehicle_type(test_type)
        if normalized:
            print_test("normalize_vehicle_type() робота", "PASS", f"'{test_type}' → '{normalized}'")
        else:
            print_test("normalize_vehicle_type() робота", "WARN", "Повертає None")
    except Exception as e:
        print_test("helpers.normalize_vehicle_type", "FAIL", f"Помилка: {e}")


def print_summary():
    """Виводить підсумок тестів"""
    print_header("ПІДСУМОК ТЕСТІВ")
    
    total = test_results["passed"] + test_results["failed"] + test_results["warnings"]
    success_rate = (test_results["passed"] / total * 100) if total > 0 else 0
    
    print(f"\n  ✅ Успішно: {test_results['passed']}")
    print(f"  ❌ Помилок: {test_results['failed']}")
    print(f"  ⚠️  Попереджень: {test_results['warnings']}")
    print(f"  📊 Всього тестів: {total}")
    print(f"  📈 Успішність: {success_rate:.1f}%")
    
    if test_results["errors"]:
        print("\n  ❌ ПОМИЛКИ:")
        for error in test_results["errors"]:
            print(f"     - {error}")
    
    print("\n" + "=" * 80)
    
    if test_results["failed"] == 0:
        print("  ✅ ВСІ КРИТИЧНІ ТЕСТИ ПРОЙДЕНО!")
    elif test_results["failed"] <= test_results["warnings"]:
        print("  ⚠️  Є НЕКРИТИЧНІ ПРОБЛЕМИ")
    else:
        print("  ❌ ЗНАЙДЕНО КРИТИЧНІ ПОМИЛКИ")
    
    print("=" * 80 + "\n")


async def main():
    """Головна функція"""
    print_header("КОМПЛЕКСНИЙ ТЕСТ РОБОТОСПРОМОЖНОСТІ VMD EXTRACTOR")
    print(f"  Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Запускаємо тести
    test_imports()
    await test_database()
    await test_trello_modules()
    await test_excel_export()
    await test_cli_modules()
    await test_config()
    await test_data_integrity()
    await test_utils()
    
    # Виводимо підсумок
    print_summary()


if __name__ == "__main__":
    asyncio.run(main())

