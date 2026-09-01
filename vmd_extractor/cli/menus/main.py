#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Головне меню VMD Extractor.
Оптимізовано: lazy imports для швидкого старту.
"""

import sys
import asyncio

from .base import BaseMenu, menu_runner
from .utils import print_header, print_menu, get_user_choice, clear_screen, wait_for_enter

# LAZY IMPORTS: Підменю імпортуються тільки коли користувач їх обирає
# Це прискорює запуск CLI з ~470ms до ~50ms


class MainMenu(BaseMenu):
    """Головне меню VMD Extractor"""
    
    async def run(self) -> None:
        """Головне меню"""
        options = {
            "1": "Управління завантажувачем",
            "2": "Управління базою даних",
            "3": "Управління Trello",
            "4": "Звіти",
            "5": "Розсилка",
            "6": "Обробка брифів",
            "0": "Вихід"
        }
        
        # LAZY IMPORTS: кожен handler імпортує своє меню тільки при виклику
        async def handler_downloader():
            from .download import show_downloader_menu
            await show_downloader_menu()
        
        async def handler_database():
            from .database import show_db_menu
            await show_db_menu()
        
        async def handler_trello():
            from .trello.menu import show_trello_menu
            await show_trello_menu()
        
        async def handler_reports():
            from .report import show_reports_menu
            await show_reports_menu()
        
        async def handler_mailing():
            from .mailing import show_mailing_menu
            await show_mailing_menu()
        
        async def handler_brief():
            from ...brief.cli import show_brief_menu
            show_brief_menu()  # Синхронне меню
        
        handlers = {
            "1": handler_downloader,
            "2": handler_database,
            "3": handler_trello,
            "4": handler_reports,
            "5": handler_mailing,
            "6": handler_brief,
        }
        
        while True:
            self.clear()
            self.show_header("VMD EXTRACTOR - ГОЛОВНЕ МЕНЮ")
            self.show_menu_options(options, "ОБЕРІТЬ РОЗДІЛ")
            choice = self.get_choice(options)
            
            if choice == "0":
                print("\nДо побачення!\n")
                break
            
            handler = handlers.get(choice)
            if handler:
                try:
                    await handler()
                    # Підменю самі обробляють wait() через run_menu_loop()
                    self.clear()
                except Exception as e:
                    print(f"\n  ❌ Помилка: {e}")
                    self.wait()
                    self.clear()


# Backward compatibility
async def main_menu():
    """Головне меню (backward compatibility)"""
    menu = MainMenu()
    await menu.run()


# Для запуску з синхронного коду
def main_menu_sync():
    """Синхронна обгортка для головного меню"""
    menu_runner.run(main_menu())
