#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль управління звітами.
Рефакторено з використанням BaseMenu для усунення дублювання.
"""

import sys
import asyncio
import traceback
from datetime import datetime

from ...config import DB_PATH
from .base import BaseMenu, async_menu_handler
from .utils import (
    print_header, print_menu, get_user_choice, clear_screen, wait_for_enter,
    get_current_week_range, get_previous_week_range, 
    get_current_month_range, get_previous_month_range, 
    get_current_quarter_range, format_date_range_ua
)


class ReportMenu(BaseMenu):
    """Меню управління звітами"""
    
    @async_menu_handler
    async def show_vmd_report(self, date_from: str, date_to: str, report_title: str) -> None:
        """Показує звіт по ВМД за вказаний період"""
        print_header(report_title)
        
        try:
            async with self.db_context() as db:
                # Отримуємо статистику
                stats = await db.get_vmd_count_by_date_range(date_from, date_to)
                
                # Форматуємо дати для відображення
                date_range_str = format_date_range_ua(date_from, date_to)
                
                print(f"\n  📅 Період: {date_range_str}")
                print(f"\n  📊 ЗАГАЛЬНА СТАТИСТИКА")
                print("  " + "─" * 50)
                print(f"  Всього ВМД за період: {stats['total']}")
                
                if stats['by_type']:
                    print(f"\n  📋 РОЗБИВКА ПО ТИПАХ АВТО")
                    print("  " + "─" * 50)
                    
                    # Сортуємо по кількості (найбільше перше)
                    sorted_types = sorted(stats['by_type'].items(), key=lambda x: x[1], reverse=True)
                    
                    for idx, (vtype, count) in enumerate(sorted_types, 1):
                        # Обмежуємо довжину типу для красивого відображення
                        vtype_display = vtype[:35] + "..." if len(vtype) > 35 else vtype
                        percentage = (count / stats['total'] * 100) if stats['total'] > 0 else 0
                        print(f"  {idx:2}. {vtype_display:<40} {count:>5} ({percentage:5.1f}%)")
                else:
                    print("\n  ℹ️  ВМД за цей період не знайдено")
                
                print("\n" + "=" * 60)
                
        except Exception as e:
            print(f"\n  ❌ Помилка: {e}")
            traceback.print_exc()
        
        # wait() викликається автоматично в run_menu_loop()
    
    @async_menu_handler
    async def show_general_stats(self) -> None:
        """Показує загальну статистику по ВМД"""
        print_header("ЗАГАЛЬНА СТАТИСТИКА ВМД")
        
        try:
            async with self.db_context() as db:
                stats = await db.get_vmd_stats_summary()
                
                print(f"\n  📊 ЗАГАЛЬНА ІНФОРМАЦІЯ")
                print("  " + "─" * 50)
                print(f"  Всього ВМД в базі даних: {stats['total']}")
                
                if stats['first_date'] and stats['last_date']:
                    first_date_str = format_date_range_ua(stats['first_date'], stats['first_date']).split(' - ')[0]
                    last_date_str = format_date_range_ua(stats['last_date'], stats['last_date']).split(' - ')[0]
                    print(f"  Перша ВМД: {first_date_str}")
                    print(f"  Остання ВМД: {last_date_str}")
                
                if stats['by_type']:
                    print(f"\n  📋 РОЗБИВКА ПО ТИПАХ АВТО (ЗА ВЕСЬ ЧАС)")
                    print("  " + "─" * 50)
                    
                    sorted_types = sorted(stats['by_type'].items(), key=lambda x: x[1], reverse=True)
                    
                    for idx, (vtype, count) in enumerate(sorted_types, 1):
                        vtype_display = vtype[:35] + "..." if len(vtype) > 35 else vtype
                        percentage = (count / stats['total'] * 100) if stats['total'] > 0 else 0
                        print(f"  {idx:2}. {vtype_display:<40} {count:>5} ({percentage:5.1f}%)")
                
                print("\n" + "=" * 60)
                
        except Exception as e:
            print(f"\n  ❌ Помилка: {e}")
            traceback.print_exc()
        
        # wait() викликається автоматично в run_menu_loop()
    
    @async_menu_handler
    async def show_custom_date_report(self) -> None:
        """Показує звіт по ВМД за довільний період"""
        print_header("ЗВІТ ЗА ДОВІЛЬНИЙ ПЕРІОД")
        
        print("\n  Введіть дати в форматі DD.MM.YYYY")
        print("  " + "─" * 40)
        
        # Отримуємо дату початку
        date_from_input = input("\n  Дата початку: ").strip()
        if not date_from_input:
            print("\n  ⚠️  Дату початку не введено")
            input("\nНатисніть Enter для продовження...")
            return
        
        # Парсимо дату початку
        try:
            date_from = datetime.strptime(date_from_input, "%d.%m.%Y").date().isoformat()
        except ValueError:
            print("\n  ❌ Невірний формат дати. Використовуйте DD.MM.YYYY")
            input("\nНатисніть Enter для продовження...")
            return
        
        # Отримуємо дату кінця
        date_to_input = input("  Дата кінця: ").strip()
        if not date_to_input:
            print("\n  ⚠️  Дату кінця не введено")
            input("\nНатисніть Enter для продовження...")
            return
        
        # Парсимо дату кінця
        try:
            date_to = datetime.strptime(date_to_input, "%d.%m.%Y").date().isoformat()
        except ValueError:
            print("\n  ❌ Невірний формат дати. Використовуйте DD.MM.YYYY")
            input("\nНатисніть Enter для продовження...")
            return
        
        # Перевіряємо що дата початку не пізніше дати кінця
        if date_from > date_to:
            print("\n  ❌ Дата початку не може бути пізніше дати кінця")
            input("\nНатисніть Enter для продовження...")
            return
        
        clear_screen()
        await self.show_vmd_report(date_from, date_to, "ЗВІТ ЗА ДОВІЛЬНИЙ ПЕРІОД")
    
    async def run(self) -> None:
        """Головне меню звітів"""
        print_header("ЗВІТИ ВМД")
        
        today = datetime.now()
        
        # Отримуємо діапазони дат для відображення в меню
        week_from, week_to = get_current_week_range()
        month_from, month_to = get_current_month_range()
        quarter_from, quarter_to = get_current_quarter_range()
        prev_week_from, prev_week_to = get_previous_week_range()
        prev_month_from, prev_month_to = get_previous_month_range()
        
        MONTHS_UA_SHORT = {
            1: "січ", 2: "лют", 3: "бер", 4: "кві",
            5: "тра", 6: "чер", 7: "лип", 8: "сер",
            9: "вер", 10: "жов", 11: "лис", 12: "гру"
        }
        
        # Визначаємо поточний квартал
        current_quarter = (today.month - 1) // 3 + 1
        
        options = {
            "1": "📊 Загальна статистика",
            "2": f"📅 Поточний тиждень",
            "3": f"📅 Попередній тиждень",
            "4": f"📆 Поточний місяць ({MONTHS_UA_SHORT[today.month]})",
            "5": f"📆 Попередній місяць",
            "6": f"🗓️  Поточний квартал (Q{current_quarter})",
            "7": "🔍 Звіт за довільний період",
            "0": "Повернутися до головного меню"
        }
        
        # Створюємо async обробники для різних звітів
        async def handler_week():
            await self.show_vmd_report(week_from, week_to, "ЗВІТ ЗА ПОТОЧНИЙ ТИЖДЕНЬ")
        
        async def handler_prev_week():
            await self.show_vmd_report(prev_week_from, prev_week_to, "ЗВІТ ЗА ПОПЕРЕДНІЙ ТИЖДЕНЬ")
        
        async def handler_month():
            await self.show_vmd_report(month_from, month_to, "ЗВІТ ЗА ПОТОЧНИЙ МІСЯЦЬ")
        
        async def handler_prev_month():
            await self.show_vmd_report(prev_month_from, prev_month_to, "ЗВІТ ЗА ПОПЕРЕДНІЙ МІСЯЦЬ")
        
        async def handler_quarter():
            await self.show_vmd_report(quarter_from, quarter_to, f"ЗВІТ ЗА ПОТОЧНИЙ КВАРТАЛ (Q{current_quarter})")
        
        handlers = {
            "1": self.show_general_stats,
            "2": handler_week,
            "3": handler_prev_week,
            "4": handler_month,
            "5": handler_prev_month,
            "6": handler_quarter,
            "7": self.show_custom_date_report,
        }
        
        await self.run_menu_loop(options, handlers, "ОБЕРІТЬ ЗВІТ")


# Функції для backward compatibility
async def show_vmd_report(date_from: str, date_to: str, report_title: str):
    """Показує звіт по ВМД за вказаний період (backward compatibility)"""
    menu = ReportMenu()
    await menu.show_vmd_report(date_from, date_to, report_title)


async def show_general_stats():
    """Показує загальну статистику по ВМД (backward compatibility)"""
    menu = ReportMenu()
    await menu.show_general_stats()


async def show_custom_date_report():
    """Показує звіт по ВМД за довільний період (backward compatibility)"""
    menu = ReportMenu()
    await menu.show_custom_date_report()


async def show_reports_menu():
    """Меню звітів (backward compatibility)"""
    menu = ReportMenu()
    await menu.run()
