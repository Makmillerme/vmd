#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI інтерфейс для обробки брифів
"""

import asyncio
import os
import sys
import concurrent.futures
from pathlib import Path
from typing import Optional

from .orchestrator import BriefOrchestrator
from .database import BriefDatabase
from ..config import DB_PATH, BRIEF_FILES_DIR


def print_header(title: str):
    """Виводить заголовок"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60 + "\n")


async def process_single_brief(imfx_path: str):
    """Обробляє один файл брифу"""
    print_header("ОБРОБКА БРИФУ")
    
    if not os.path.exists(imfx_path):
        print(f"  Помилка: Файл не знайдено: {imfx_path}")
        return
    
    print(f"  Файл: {os.path.basename(imfx_path)}")
    print(f"  Шлях: {imfx_path}\n")
    
    orchestrator = BriefOrchestrator(DB_PATH)
    result = await orchestrator.process_brief_file(imfx_path)
    
    if result['success']:
        print("\n  ✓ Бриф успішно оброблено!")
        print(f"  VIN: {result.get('vin', 'N/A')}")
        print(f"  PDF: {result.get('pdf_path', 'N/A')}")
        if result.get('brief_id'):
            print(f"  ID в БД: {result['brief_id']}")
    else:
        print(f"\n  ✗ Помилка обробки: {result.get('error', 'Unknown error')}")


async def list_briefs(limit: int = 20):
    """Виводить список брифів"""
    print_header("СПИСОК БРИФІВ")
    
    db = BriefDatabase(DB_PATH)
    briefs = await db.get_all_briefs(limit=limit)
    
    if not briefs:
        print("  Брифів не знайдено.")
        return
    
    print(f"  Знайдено {len(briefs)} брифів:\n")
    print("  №  | Файл | VIN | PDF")
    print("  " + "-" * 60)
    
    for idx, brief in enumerate(briefs, 1):
        source_file = brief.get('source_file', 'N/A')
        vin = brief.get('vin', 'N/A')
        pdf_path = brief.get('pdf_path', 'N/A')
        if pdf_path and pdf_path != 'N/A':
            pdf_path = os.path.basename(pdf_path)
        print(f"  {idx:>2} | {source_file[:30]:<30} | {vin[:17]:<17} | {pdf_path}")


async def search_brief_by_vin(vin: str):
    """Шукає бриф за VIN"""
    print_header("ПОШУК БРИФУ ЗА VIN")
    
    if not vin:
        print("  Помилка: VIN не вказано")
        return
    
    print(f"  VIN: {vin}\n")
    
    db = BriefDatabase(DB_PATH)
    brief = await db.get_brief_by_vin(vin)
    
    if brief:
        print("  ✓ Бриф знайдено:\n")
        print(f"  Файл: {brief.get('source_file', 'N/A')}")
        print(f"  VIN: {brief.get('vin', 'N/A')}")
        print(f"  PDF: {brief.get('pdf_path', 'N/A')}")
        print(f"  Створено: {brief.get('created_at', 'N/A')}")
        images = brief.get('images', [])
        if images:
            print(f"  Фото: {len(images)} зображень")
    else:
        print("  ✗ Бриф не знайдено")


async def process_from_google_drive():
    """Завантажує та обробляє файли з Google Drive"""
    print_header("ЗАВАНТАЖЕННЯ ТА ОБРОБКА З GOOGLE DRIVE")
    
    try:
        use_api_input = input("  Використати API для оновлення статусу? (y/n, за замовчуванням n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        use_api_input = 'n'
    
    use_api = use_api_input == 'y'
    
    try:
        status_filter_input = input("  Фільтр по статусу (PENDING/DOWNLOADED/PROCESSED, Enter для всіх): ").strip()
    except (EOFError, KeyboardInterrupt):
        status_filter_input = ''
    
    status_filter = status_filter_input if status_filter_input else None
    
    try:
        cleanup = input("  Видалити завантажені файли після обробки? (y/n, за замовчуванням y): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        cleanup = 'y'
    
    cleanup_after = cleanup != 'n'
    
    print(f"\n  Режим: {'API (з оновленням статусу)' if use_api else 'Пряме завантаження (швидше)'}")
    if status_filter:
        print(f"  Фільтр статусу: {status_filter}")
    print(f"  Очищення після обробки: {'Так' if cleanup_after else 'Ні'}\n")
    
    orchestrator = BriefOrchestrator(DB_PATH)
    results = await orchestrator.process_files_from_google_drive(
        use_api=use_api,
        status_filter=status_filter,
        cleanup_after=cleanup_after
    )
    
    print("\n  Результати обробки:")
    print(f"  Завантажено: {results['downloaded']}")
    print(f"  Оброблено: {results['processed']}")
    print(f"  Успішно: {results['successful']}")
    print(f"  Помилок: {results['failed']}")
    
    if results.get('excel_path'):
        print(f"\n  ✓ Excel оновлено: {os.path.basename(results['excel_path'])}")
    
    if results['errors']:
        print("\n  Помилки:")
        for error in results['errors'][:10]:  # Показуємо перші 10
            print(f"    - {error}")
        if len(results['errors']) > 10:
            print(f"    ... та ще {len(results['errors']) - 10} помилок")


async def process_local_files():
    """Обробляє всі файли з локальної папки"""
    print_header("ОБРОБКА ЛОКАЛЬНИХ ФАЙЛІВ")
    
    try:
        files_dir = input("  Введіть шлях до папки з файлами (Enter для папки за замовчуванням): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Операцію скасовано.")
        return
    
    if files_dir:
        print(f"\n  Папка: {files_dir}")
    else:
        from ..config import BRIEF_FILES_DIR
        files_dir = str(BRIEF_FILES_DIR)
        print(f"\n  Використовується папка за замовчуванням: {files_dir}")
    
    print()
    
    orchestrator = BriefOrchestrator(DB_PATH)
    results = await orchestrator.process_local_files(files_dir)
    
    print("\n  Результати обробки:")
    print(f"  Знайдено: {results['found']}")
    print(f"  Оброблено: {results['processed']}")
    print(f"  Успішно: {results['successful']}")
    print(f"  Помилок: {results['failed']}")
    
    if results.get('excel_path'):
        print(f"\n  ✓ Excel оновлено: {os.path.basename(results['excel_path'])}")
    
    if results['errors']:
        print("\n  Помилки:")
        for error in results['errors'][:10]:  # Показуємо перші 10
            print(f"    - {error}")
        if len(results['errors']) > 10:
            print(f"    ... та ще {len(results['errors']) - 10} помилок")


def _run_async_safe(coro):
    """
    Безпечний запуск async функції, навіть якщо вже є запущений event loop.
    
    Args:
        coro: Coroutine для виконання
    """
    try:
        # Перевіряємо чи є запущений event loop
        loop = asyncio.get_running_loop()
        # Якщо є - створюємо новий event loop в окремому потоці
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            future.result()
    except RuntimeError:
        # Немає запущеного event loop - можна використати asyncio.run()
        asyncio.run(coro)


def wait_for_enter(message: str = "\n  Натисніть Enter для продовження..."):
    """Безпечне очікування натискання Enter з обробкою помилок"""
    try:
        input(message)
    except (EOFError, KeyboardInterrupt, OSError):
        # stdin закритий або перерваний - просто продовжуємо
        print()  # Додаємо новий рядок для коректного форматування
        pass


def get_user_choice_safe(options: dict) -> str:
    """Отримання вибору користувача з обробкою помилок"""
    while True:
        try:
            choice = input("  Ваш вибір: ").strip()
            if choice in options:
                return choice
            print(f"  Помилка: невірний вибір. Оберіть один з: {', '.join(options.keys())}")
        except (EOFError, KeyboardInterrupt):
            # Якщо stdin закритий, повертаємо "0" для виходу
            print("\n  Переривання вводу. Повертаємось до меню...")
            return "0"


def show_brief_menu():
    """Головне меню обробки брифів"""
    while True:
        try:
            print_header("ОБРОБКА БРИФІВ")
            
            options = {
                "1": "Обробити файл брифу",
                "2": "Завантажити та обробити з Google Drive",
                "3": "Обробити локальні файли",
                "4": "Список брифів",
                "5": "Пошук за VIN",
                "0": "Повернутися назад"
            }
            
            for key, label in options.items():
                print(f"  {key}. {label}")
            print()
            
            choice = get_user_choice_safe(options)
            
            if choice == "0":
                break
            elif choice == "1":
                try:
                    file_path = input("  Введіть шлях до .imfx файлу: ").strip()
                    if file_path:
                        _run_async_safe(process_single_brief(file_path))
                except (EOFError, KeyboardInterrupt):
                    print("\n  Операцію скасовано.")
                wait_for_enter()
            elif choice == "2":
                try:
                    _run_async_safe(process_from_google_drive())
                except (EOFError, KeyboardInterrupt):
                    print("\n  Операцію скасовано.")
                except Exception as e:
                    print(f"\n  Помилка: {e}")
                    import traceback
                    traceback.print_exc()
                wait_for_enter()
            elif choice == "3":
                try:
                    _run_async_safe(process_local_files())
                except (EOFError, KeyboardInterrupt):
                    print("\n  Операцію скасовано.")
                except Exception as e:
                    print(f"\n  Помилка: {e}")
                    import traceback
                    traceback.print_exc()
                wait_for_enter()
            elif choice == "4":
                try:
                    limit_input = input("  Кількість записів (за замовчуванням 20): ").strip()
                    limit = int(limit_input) if limit_input.isdigit() else 20
                    _run_async_safe(list_briefs(limit))
                except (EOFError, KeyboardInterrupt):
                    print("\n  Операцію скасовано.")
                except Exception as e:
                    print(f"\n  Помилка: {e}")
                    import traceback
                    traceback.print_exc()
                wait_for_enter()
            elif choice == "5":
                try:
                    vin = input("  Введіть VIN: ").strip()
                    if vin:
                        _run_async_safe(search_brief_by_vin(vin))
                except (EOFError, KeyboardInterrupt):
                    print("\n  Операцію скасовано.")
                except Exception as e:
                    print(f"\n  Помилка: {e}")
                    import traceback
                    traceback.print_exc()
                wait_for_enter()
            else:
                print("  Невірний вибір. Спробуйте ще раз.")
                wait_for_enter()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Повертаємось до головного меню...")
            break
        except Exception as e:
            print(f"\n  Критична помилка: {e}")
            import traceback
            traceback.print_exc()
            wait_for_enter()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Обробка файлу з командного рядка
        asyncio.run(process_single_brief(sys.argv[1]))
    else:
        # Інтерактивне меню
        show_brief_menu()

