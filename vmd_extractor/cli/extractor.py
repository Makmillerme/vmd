#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт запуску VMD Extractor з підтримкою фільтрації по даті
"""

import asyncio
import sys
import os
import logging
import argparse
from datetime import date, timedelta

# Додаємо поточну директорію до шляху
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vmd_extractor.core.orchestrator import VMDOrchestrator
from vmd_extractor.cli.report import get_vmd_count_report

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Встановлюємо рівень логування для модулів
logging.getLogger("vmd_extractor").setLevel(logging.INFO)


def parse_date(date_str: str) -> date:
    """Парсинг дати з рядка формату YYYY-MM-DD"""
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Невірний формат дати: {date_str}. Використовуйте YYYY-MM-DD (наприклад, 2025-01-15)")


def parse_arguments():
    """Парсинг аргументів командного рядка"""
    parser = argparse.ArgumentParser(
        description="VMD Extractor - Асинхронна система обробки ВМД з підтримкою фільтрації по даті",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Приклади використання:

  # ШВИДКІ КОМАНДИ:
  python run.py --week          # Завантаження за останні 7 днів
  python run.py --month         # Завантаження за останні 30 днів
  python run.py --current-month # Завантаження за поточний місяць (з 1 числа до сьогодні)

  # ДІАПАЗОН ДАТ:
  python run.py --from 2025-01-01 --to 2025-01-31  # Конкретний проміжок
  python run.py --from 2025-01-01                  # З конкретної дати до сьогодні
  python run.py --to 2025-01-31                    # Всі дані до зазначеної дати

  # КЕРУВАННЯ СОРТУВАННЯМ:
  python run.py --week --no-sort                   # Вимкнути сортування для швидкої команди
        """
    )
    
    # Параметри дат
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument(
        "--week",
        action="store_true",
        help="Завантажити ВМД за останні 7 днів"
    )
    date_group.add_argument(
        "--month",
        action="store_true",
        help="Завантажити ВМД за останні 30 днів"
    )
    date_group.add_argument(
        "--current-month",
        action="store_true",
        help="Завантажити ВМД за поточний місяць (з 1 числа поточного місяця до сьогодні)"
    )
    date_group.add_argument(
        "--from",
        dest="date_from",
        type=parse_date,
        metavar="YYYY-MM-DD",
        help="Початкова дата фільтрації (включно). Формат: YYYY-MM-DD"
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        type=parse_date,
        metavar="YYYY-MM-DD",
        help="Кінцева дата фільтрації (включно). Формат: YYYY-MM-DD"
    )
    
    # Інші параметри
    parser.add_argument(
        "--no-sort",
        action="store_true",
        help="Не сортувати повідомлення по даті (за замовчуванням: сортування увімкнено, від новіших до старіших)"
    )
    
    return parser.parse_args()


async def main():
    """Головна функція"""
    args = parse_arguments()
    
    # Визначаємо дати на основі аргументів
    date_from = None
    date_to = None
    today = date.today()
    
    if args.week:
        # Останні 7 днів
        date_from = today - timedelta(days=6)  # Включаємо сьогодні, тому 6 днів назад
        date_to = today
    elif args.month:
        # Останні 30 днів
        date_from = today - timedelta(days=29)  # Включаємо сьогодні, тому 29 днів назад
        date_to = today
    elif args.current_month:
        # Поточний місяць: з 1 числа поточного місяця до сьогодні
        date_from = date(today.year, today.month, 1)
        date_to = today
    else:
        date_from = args.date_from
        date_to = args.date_to
    
    # Визначаємо сортування
    sort_by_date = not args.no_sort
    
    # Виводимо інформацію про режим роботи
    print("="*60)
    print("VMD EXTRACTOR - Асинхронна система обробки ВМД")
    print("="*60)
    
    if date_from or date_to:
        date_info = []
        mode_name = ""
        
        # Визначаємо назву режиму для швидких команд
        if args.week:
            mode_name = " (Останні 7 днів)"
        elif args.month:
            mode_name = " (Останні 30 днів)"
        elif args.current_month:
            mode_name = " (Поточний місяць)"
        
        if date_from:
            date_info.append(f"від {date_from.strftime('%Y-%m-%d')}")
        if date_to:
            date_info.append(f"до {date_to.strftime('%Y-%m-%d')}")
        print(f"Режим: Завантаження ВСІХ ВМД за діапазон {' '.join(date_info)}{mode_name}")
    else:
        print("Режим: Завантаження ВСІХ доступних ВМД (без фільтрації по даті)")
    
    print(f"Сортування: {'від новіших до старіших' if sort_by_date else 'вимкнено'}")
    print("="*60)
    print()
    
    # Крок 0: Перевірка наявності ВМД за вказаний діапазон
    vmd_uids = None
    if date_from or date_to:
        print("Перевірка наявності ВМД на пошті...")
        print()
        vmd_report, vmd_uids = get_vmd_count_report(date_from, date_to, show_details=True)
        total_vmd_count = sum(vmd_report.values())
        
        if total_vmd_count == 0:
            print("\nВМД не знайдено за вказаний діапазон дат. Завантаження не буде виконано.")
            return {
                "downloaded": 0,
                "processed": 0,
                "parsed_records": 0,
                "excel_path": None,
                "errors": []
            }
        
        print(f"\nЗнайдено {total_vmd_count} ВМД для завантаження.")
        print("Починаємо завантаження...")
        print()
    
    # Створюємо оркестратор з параметрами
    orchestrator = VMDOrchestrator(
        date_from=date_from,
        date_to=date_to,
        sort_by_date=sort_by_date
    )
    
    # Запускаємо пайплайн з передачею UID (якщо є)
    results = await orchestrator.run_full_pipeline(vmd_uids=vmd_uids)
    
    # Виводимо результати
    print("\n" + "="*60)
    print("РЕЗУЛЬТАТИ:")
    print("="*60)
    print(f"Завантажено файлів: {results['downloaded']}")
    print(f"Оброблено файлів: {results['processed']}")
    print(f"Спарсено записів: {results['parsed_records']}")
    print(f"Excel файл: {results['excel_path']}")
    
    if results['errors']:
        print(f"\nПомилки: {len(results['errors'])}")
        for error in results['errors']:
            print(f"  - {error}")
    
    print("="*60)
    
    return results


if __name__ == "__main__":
    try:
        results = asyncio.run(main())
        sys.exit(0 if results['parsed_records'] > 0 else 1)
    except KeyboardInterrupt:
        print("\n\nОперацію скасовано користувачем")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nКритична помилка: {e}")
        logging.exception("Critical error")
        sys.exit(1)



