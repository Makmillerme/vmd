#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Меню завантажувача.
Оптимізовано: 4 опції замість 8, з prompt про Trello.
"""

import asyncio
from datetime import date, timedelta
from typing import Optional

from vmd_extractor.core.orchestrator import VMDOrchestrator
from vmd_extractor.cli.report import get_vmd_count_report

from .base import BaseMenu, async_menu_handler
from .utils import (
    print_header, print_menu, get_user_choice, 
    wait_for_enter, clear_screen, get_date_input, get_date_input_optional
)


def _ask_trello_sync() -> bool:
    """Запитує користувача чи створювати картки в Trello"""
    try:
        answer = input("\n  Створювати картки в Trello? (y/n, за замовчуванням y): ").strip().lower()
        return answer != 'n'
    except (EOFError, KeyboardInterrupt):
        return True  # За замовчуванням - з Trello


def _ask_sync_existing_trello_cards() -> bool:
    """Запитує чи синхронізувати дані всіх існуючих карток з Trello (довга операція). За замовчуванням n."""
    try:
        answer = input("  Синхронізувати дані всіх існуючих карток з Trello? (y/n, за замовчуванням n): ").strip().lower()
        return answer == 'y'
    except (EOFError, KeyboardInterrupt):
        return False


async def run_downloader_with_dates(
    date_from: date, 
    date_to: date, 
    mode_name: str = "", 
    skip_trello: bool = False
) -> Optional[dict]:
    """Загальна функція для завантаження з датами"""
    print(f"\n  Діапазон: {date_from.strftime('%d.%m.%Y')} - {date_to.strftime('%d.%m.%Y')}{mode_name}")
    if skip_trello:
        print("  Режим: збереження лише в БД (без Trello)")
    else:
        print("  Режим: БД + створення карток в Trello")
    
    # Перевірка наявності ВМД
    print("\n  Перевірка наявності ВМД на пошті...")
    vmd_report, vmd_uids = get_vmd_count_report(date_from, date_to, show_details=False, show_progress=True)
    total_vmd_count = sum(vmd_report.values())
    
    sync_existing_cards = False
    if not skip_trello:
        sync_existing_cards = _ask_sync_existing_trello_cards()

    if total_vmd_count == 0:
        print("  ВМД на пошті за діапазон не знайдено.")
        if skip_trello:
            print("  Нових даних для завантаження немає.")
            return None
        print("  Продовжуємо оновлення БД, Excel і Trello...\n")
        vmd_uids = None
    else:
        print(f"\n  Знайдено {total_vmd_count} ВМД для завантаження.\n")

    # Запуск пайплайну
    orchestrator = VMDOrchestrator(
        date_from=date_from,
        date_to=date_to,
        sort_by_date=True
    )
    results = await orchestrator.run_full_pipeline(
        vmd_uids=vmd_uids,
        skip_trello=skip_trello,
        sync_existing_trello_cards=sync_existing_cards,
    )
    return results


class DownloaderMenu(BaseMenu):
    """Меню управління завантажувачем"""
    
    @async_menu_handler
    async def run_downloader_week(self) -> Optional[dict]:
        """Завантаження за останні 7 днів"""
        print_header("ЗАВАНТАЖЕННЯ ЗА ОСТАННІ 7 ДНІВ")
        today = date.today()
        date_from = today - timedelta(days=6)
        date_to = today
        
        skip_trello = not _ask_trello_sync()
        return await run_downloader_with_dates(date_from, date_to, " (Останні 7 днів)", skip_trello)
    
    @async_menu_handler
    async def run_downloader_month(self) -> Optional[dict]:
        """Завантаження за останні 30 днів"""
        print_header("ЗАВАНТАЖЕННЯ ЗА ОСТАННІ 30 ДНІВ")
        today = date.today()
        date_from = today - timedelta(days=29)
        date_to = today
        
        skip_trello = not _ask_trello_sync()
        return await run_downloader_with_dates(date_from, date_to, " (Останні 30 днів)", skip_trello)
    
    @async_menu_handler
    async def run_downloader_current_month(self) -> Optional[dict]:
        """Завантаження за поточний місяць"""
        print_header("ЗАВАНТАЖЕННЯ ЗА ПОТОЧНИЙ МІСЯЦЬ")
        today = date.today()
        date_from = date(today.year, today.month, 1)
        date_to = today
        
        skip_trello = not _ask_trello_sync()
        return await run_downloader_with_dates(date_from, date_to, " (Поточний місяць)", skip_trello)
    
    @async_menu_handler
    async def run_downloader_custom_range(self) -> Optional[dict]:
        """Завантаження за кастомний діапазон"""
        print_header("ЗАВАНТАЖЕННЯ ЗА ДІАПАЗОН ДАТ")
        try:
            date_from = get_date_input("Введіть початкову дату")
            date_to = get_date_input_optional(
                "Введіть кінцеву дату (DD.MM.YYYY або Enter для сьогодні)",
                default_if_empty=date.today(),
            )
            if date_to is None:
                date_to = date.today()
            if date_from > date_to:
                print("  Початкова дата не може бути пізніше кінцевої!")
                return None
            
            skip_trello = not _ask_trello_sync()
            return await run_downloader_with_dates(date_from, date_to, "", skip_trello)
        except (EOFError, KeyboardInterrupt):
            print("\n  Операцію скасовано користувачем")
            return None
    
    async def run(self) -> None:
        """Головне меню управління завантажувачем"""
        options = {
            "1": "Завантажити за останні 7 днів",
            "2": "Завантажити за останні 30 днів",
            "3": "Завантажити за поточний місяць",
            "4": "Завантажити за діапазон дат",
            "0": "Повернутися до головного меню"
        }
        
        handlers = {
            "1": self.run_downloader_week,
            "2": self.run_downloader_month,
            "3": self.run_downloader_current_month,
            "4": self.run_downloader_custom_range,
        }
        
        await self.run_menu_loop(options, handlers, "УПРАВЛІННЯ ЗАВАНТАЖУВАЧЕМ")


# Функції для backward compatibility
async def run_downloader_week(skip_trello: bool = False):
    """Завантаження за останні 7 днів (backward compatibility)"""
    today = date.today()
    date_from = today - timedelta(days=6)
    return await run_downloader_with_dates(date_from, today, " (Останні 7 днів)", skip_trello)


async def run_downloader_month(skip_trello: bool = False):
    """Завантаження за останні 30 днів (backward compatibility)"""
    today = date.today()
    date_from = today - timedelta(days=29)
    return await run_downloader_with_dates(date_from, today, " (Останні 30 днів)", skip_trello)


async def run_downloader_current_month(skip_trello: bool = False):
    """Завантаження за поточний місяць (backward compatibility)"""
    today = date.today()
    date_from = date(today.year, today.month, 1)
    return await run_downloader_with_dates(date_from, today, " (Поточний місяць)", skip_trello)


async def run_downloader_custom_range(date_from: date, date_to: date, skip_trello: bool = False):
    """Завантаження за кастомний діапазон (backward compatibility)"""
    return await run_downloader_with_dates(date_from, date_to, "", skip_trello)


# Legacy aliases for backward compatibility
async def run_downloader_week_db_only():
    return await run_downloader_week(skip_trello=True)

async def run_downloader_month_db_only():
    return await run_downloader_month(skip_trello=True)

async def run_downloader_current_month_db_only():
    return await run_downloader_current_month(skip_trello=True)


async def show_downloader_menu():
    """Меню управління завантажувачем (backward compatibility)"""
    menu = DownloaderMenu()
    await menu.run()
