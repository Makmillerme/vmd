#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Головне меню Trello.
"""

from .base import BaseTrelloMenu
from .sync import sync_vehicles_to_trello
from .cards import show_trello_stats, verify_trello_links, add_trello_cards_by_vins
from .labels import show_trello_labels_menu
from .custom_fields import sync_custom_fields_for_all_cards, check_and_fix_custom_fields_for_all_cards
from ..utils import print_header, print_menu, get_user_choice, get_date_input


class TrelloMenu(BaseTrelloMenu):
    """Головне меню управління Trello"""
    
    async def run(self) -> None:
        """Головне меню Trello"""
        if not self.check_trello_enabled():
            return
        
        print_header("УПРАВЛІННЯ TRELLO")
        
        options = {
            "1": "Синхронізувати з дати",
            "2": "Синхронізувати всі несинхронізовані",
            "3": "Показати статистику Trello",
            "4": "Перевірити відповідність карток",
            "5": "Додати картки за VIN",
            "6": "Управління мітками Trello",
            "7": "Синхронізувати кастомні поля для всіх карток",
            "8": "Перевірити та виправити кастомні поля для всіх карток",
            "0": "Повернутися до головного меню"
        }
        
        handlers = {
            "1": self._handle_sync_from_date,
            "2": self._handle_sync_all,
            "3": show_trello_stats,
            "4": verify_trello_links,
            "5": add_trello_cards_by_vins,
            "6": show_trello_labels_menu,
            "7": sync_custom_fields_for_all_cards,
            "8": check_and_fix_custom_fields_for_all_cards,
        }
        
        await self.run_menu_loop(options, handlers, "ОБЕРІТЬ ОПЦІЮ")
    
    async def _handle_sync_all(self) -> None:
        """Синхронізація всіх несинхронізованих"""
        await sync_vehicles_to_trello(date_from=None)
    
    async def _handle_sync_from_date(self) -> None:
        """Обробник синхронізації з дати"""
        date_from = get_date_input("Введіть дату початку синхронізації")
        if date_from:
            date_to_input = input("Введіть дату кінця синхронізації (DD.MM.YYYY, або Enter для пропуску): ").strip()
            date_to = None
            if date_to_input:
                try:
                    from datetime import datetime
                    date_to = datetime.strptime(date_to_input, "%d.%m.%Y").date()
                except ValueError:
                    print("  Невірний формат дати. Використовується тільки дата початку.")
                    date_to = None
            await sync_vehicles_to_trello(date_from=date_from, date_to=date_to)
        else:
            print("  Дата початку обов'язкова для синхронізації з дати.")


# Backward compatibility
async def show_trello_menu():
    """Меню управління Trello (backward compatibility)"""
    menu = TrelloMenu()
    await menu.run()



