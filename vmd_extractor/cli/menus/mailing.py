#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль управління розсилкою звітів.
Оптимізовано: використовує run_menu_loop() для консистентності.
"""

import sys
import smtplib
import asyncio
import traceback
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from ...config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, 
    SMTP_FROM_NAME, EMAIL_RECIPIENTS, PDF_DIR, DB_PATH
)
from .base import BaseMenu, async_menu_handler
from .utils import (
    print_header, print_menu, get_user_choice, clear_screen, wait_for_enter,
    get_current_week_range, get_previous_week_range, 
    get_current_month_range, get_previous_month_range, 
    format_date_range_ua
)


def _confirm_send(date_range_str: str) -> bool:
    """Запитує підтвердження відправки"""
    try:
        print(f"\n  Період: {date_range_str}")
        confirm = input("\n  Відправити звіт? (y/n): ").strip().lower()
        return confirm == 'y' or confirm == 'yes'
    except (EOFError, KeyboardInterrupt):
        return False


class MailingMenu(BaseMenu):
    """Меню управління розсилкою"""
    
    def _check_smtp_config(self) -> bool:
        """Перевіряє налаштування SMTP"""
        if not SMTP_USER or not SMTP_PASS:
            print("\n  Розсилка не налаштована!")
            print("  Додайте в .env файл:")
            print("    SMTP_HOST=smtp.ukr.net")
            print("    SMTP_PORT=465")
            print("    SMTP_USER=your@email.com")
            print("    SMTP_PASS=your_password")
            print("    EMAIL=recipient1@email.com,recipient2@email.com")
            return False
        
        if not EMAIL_RECIPIENTS:
            print("\n  Не вказані отримувачі!")
            print("  Додайте EMAIL=email1@example.com,email2@example.com в .env")
            return False
        
        return True
    
    def _show_settings(self) -> None:
        """Показує поточні налаштування"""
        print("\n  НАЛАШТУВАННЯ РОЗСИЛКИ")
        print("  " + "-" * 40)
        if SMTP_USER:
            print(f"  Відправник: {SMTP_USER}")
        else:
            print("  SMTP не налаштовано")
        
        if EMAIL_RECIPIENTS:
            print(f"  Отримувачі ({len(EMAIL_RECIPIENTS)}):")
            for email in EMAIL_RECIPIENTS[:3]:  # Показуємо перші 3
                print(f"    - {email}")
            if len(EMAIL_RECIPIENTS) > 3:
                print(f"    ... та ще {len(EMAIL_RECIPIENTS) - 3}")
        else:
            print("  Отримувачі не вказані")
        print()
    
    @async_menu_handler
    async def send_vmd_report_email(self, date_from: str, date_to: str, report_title: str) -> bool:
        """Відправляє email зі звітом та PDF вкладеннями"""
        
        if not self._check_smtp_config():
            return False
        
        try:
            async with self.db_context() as db:
                # Отримуємо статистику та список ВМД
                stats = await db.get_vmd_count_by_date_range(date_from, date_to)
                vmd_list = await db.get_vmd_list_by_date_range(date_from, date_to, limit=500)
                
                if stats['total'] == 0:
                    print(f"\n  ВМД за період {date_from} - {date_to} не знайдено")
                    return False
                
                date_range_str = format_date_range_ua(date_from, date_to)
                
                # Формуємо текст звіту
                report_text = f"""
{report_title}
{'=' * 60}

Період: {date_range_str}
Дата формування: {datetime.now().strftime('%d.%m.%Y %H:%M')}

ЗАГАЛЬНА СТАТИСТИКА
{'-' * 40}
Всього ВМД за період: {stats['total']}

РОЗБИВКА ПО ТИПАХ АВТО
{'-' * 40}
"""
                sorted_types = sorted(stats['by_type'].items(), key=lambda x: x[1], reverse=True)
                for idx, (vtype, count) in enumerate(sorted_types, 1):
                    percentage = (count / stats['total'] * 100) if stats['total'] > 0 else 0
                    report_text += f"{idx}. {vtype}: {count} ({percentage:.1f}%)\n"
                
                report_text += f"""
СПИСОК ВМД
{'-' * 40}
"""
                for idx, vmd in enumerate(vmd_list, 1):
                    brand = vmd.get('brand', '')
                    model = vmd.get('model', '')
                    vin = vmd.get('vin', '')
                    vtype = vmd.get('vehicle_type', '')
                    date_ccd = vmd.get('create_at_ccd', '')
                    report_text += f"{idx}. {brand} {model} | VIN: {vin} | Тип: {vtype} | Дата: {date_ccd}\n"
                
                # HTML версія
                report_html = f"""
<html>
<head>
<style>
    body {{ font-family: Arial, sans-serif; margin: 20px; }}
    h1 {{ color: #2c3e50; }}
    h2 {{ color: #34495e; border-bottom: 2px solid #3498db; padding-bottom: 5px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #3498db; color: white; }}
    tr:nth-child(even) {{ background-color: #f9f9f9; }}
    .summary {{ background-color: #ecf0f1; padding: 15px; border-radius: 5px; margin: 15px 0; }}
    .total {{ font-size: 24px; font-weight: bold; color: #27ae60; }}
</style>
</head>
<body>
<h1>{report_title}</h1>
<p><strong>Період:</strong> {date_range_str}</p>
<p><strong>Дата формування:</strong> {datetime.now().strftime('%d.%m.%Y %H:%M')}</p>

<div class="summary">
    <p class="total">Всього ВМД: {stats['total']}</p>
</div>

<h2>Розбивка по типах авто</h2>
<table>
<tr><th>#</th><th>Тип авто</th><th>Кількість</th><th>%</th></tr>
"""
                for idx, (vtype, count) in enumerate(sorted_types, 1):
                    percentage = (count / stats['total'] * 100) if stats['total'] > 0 else 0
                    report_html += f"<tr><td>{idx}</td><td>{vtype}</td><td>{count}</td><td>{percentage:.1f}%</td></tr>\n"
                
                report_html += """
</table>

<h2>Список ВМД</h2>
<table>
<tr><th>#</th><th>Марка/Модель</th><th>VIN</th><th>Тип</th><th>Дата ВМД</th></tr>
"""
                for idx, vmd in enumerate(vmd_list, 1):
                    brand = vmd.get('brand', '')
                    model = vmd.get('model', '')
                    vin = vmd.get('vin', '')
                    vtype = vmd.get('vehicle_type', '')
                    date_ccd = vmd.get('create_at_ccd', '')
                    report_html += f"<tr><td>{idx}</td><td>{brand} {model}</td><td>{vin}</td><td>{vtype}</td><td>{date_ccd}</td></tr>\n"
                
                report_html += """
</table>
</body>
</html>
"""
                
                # Збираємо PDF файли
                pdf_files = []
                for vmd in vmd_list:
                    vin = vmd.get('vin', '')
                    mrn = vmd.get('mrn', '')
                    if vin:
                        for pdf_path in PDF_DIR.glob(f"*{vin}*.pdf"):
                            if pdf_path.exists() and pdf_path not in pdf_files:
                                pdf_files.append(pdf_path)
                    if mrn:
                        for pdf_path in PDF_DIR.glob(f"*{mrn}*.pdf"):
                            if pdf_path.exists() and pdf_path not in pdf_files:
                                pdf_files.append(pdf_path)
                
                print(f"\n  Знайдено PDF файлів: {len(pdf_files)}")
                
                # Створюємо email
                msg = MIMEMultipart('alternative')
                msg['Subject'] = f"{report_title} ({date_range_str})"
                msg['From'] = f"{SMTP_FROM_NAME} <{SMTP_USER}>"
                msg['To'] = ", ".join(EMAIL_RECIPIENTS)
                
                msg.attach(MIMEText(report_text, 'plain', 'utf-8'))
                msg.attach(MIMEText(report_html, 'html', 'utf-8'))
                
                # Multipart для вкладень
                msg_with_attachments = MIMEMultipart('mixed')
                msg_with_attachments['Subject'] = msg['Subject']
                msg_with_attachments['From'] = msg['From']
                msg_with_attachments['To'] = msg['To']
                msg_with_attachments.attach(msg)
                
                # Додаємо PDF (макс 50)
                attached_count = 0
                max_attachments = 50
                for pdf_path in pdf_files[:max_attachments]:
                    try:
                        with open(pdf_path, 'rb') as f:
                            part = MIMEBase('application', 'pdf')
                            part.set_payload(f.read())
                            encoders.encode_base64(part)
                            part.add_header('Content-Disposition', f'attachment; filename="{pdf_path.name}"')
                            msg_with_attachments.attach(part)
                            attached_count += 1
                    except Exception as e:
                        print(f"  Не вдалося додати {pdf_path.name}: {e}")
                
                if len(pdf_files) > max_attachments:
                    print(f"  Додано лише {max_attachments} з {len(pdf_files)} PDF (ліміт)")
                
                print(f"  Додано вкладень: {attached_count}")
                print(f"\n  Відправка на: {', '.join(EMAIL_RECIPIENTS)}")
                
                with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
                    server.login(SMTP_USER, SMTP_PASS)
                    server.sendmail(SMTP_USER, EMAIL_RECIPIENTS, msg_with_attachments.as_string())
                
                print("\n  Email успішно відправлено!")
                return True
                
        except smtplib.SMTPAuthenticationError:
            print("\n  Помилка авторизації SMTP")
            print("  Перевірте SMTP_USER та SMTP_PASS")
            return False
        except smtplib.SMTPException as e:
            print(f"\n  Помилка SMTP: {e}")
            return False
        except Exception as e:
            print(f"\n  Помилка: {e}")
            traceback.print_exc()
            return False
    
    async def _send_current_week(self) -> None:
        """Відправка ВМД за поточний тиждень"""
        week_from, week_to = get_current_week_range()
        date_range_str = format_date_range_ua(week_from, week_to)
        
        if _confirm_send(date_range_str):
            await self.send_vmd_report_email(week_from, week_to, "Звіт ВМД за поточний тиждень")
    
    async def _send_prev_week(self) -> None:
        """Відправка ВМД за минулий тиждень"""
        prev_week_from, prev_week_to = get_previous_week_range()
        date_range_str = format_date_range_ua(prev_week_from, prev_week_to)
        
        if _confirm_send(date_range_str):
            await self.send_vmd_report_email(prev_week_from, prev_week_to, "Звіт ВМД за минулий тиждень")
    
    async def _send_current_month(self) -> None:
        """Відправка ВМД за поточний місяць"""
        month_from, month_to = get_current_month_range()
        date_range_str = format_date_range_ua(month_from, month_to)
        
        if _confirm_send(date_range_str):
            await self.send_vmd_report_email(month_from, month_to, "Звіт ВМД за поточний місяць")
    
    async def _send_prev_month(self) -> None:
        """Відправка ВМД за минулий місяць"""
        prev_month_from, prev_month_to = get_previous_month_range()
        date_range_str = format_date_range_ua(prev_month_from, prev_month_to)
        
        if _confirm_send(date_range_str):
            await self.send_vmd_report_email(prev_month_from, prev_month_to, "Звіт ВМД за минулий місяць")
    
    async def run(self) -> None:
        """Головне меню розсилки"""
        
        options = {
            "1": "Відправити ВМД за поточний тиждень",
            "2": "Відправити ВМД за минулий тиждень",
            "3": "Відправити ВМД за поточний місяць",
            "4": "Відправити ВМД за минулий місяць",
            "0": "Повернутися до головного меню"
        }
        
        handlers = {
            "1": self._send_current_week,
            "2": self._send_prev_week,
            "3": self._send_current_month,
            "4": self._send_prev_month,
        }
        
        # Показуємо налаштування перед меню
        while True:
            self.clear()
            self.show_header("РОЗСИЛКА ВМД")
            self._show_settings()
            self.show_menu_options(options, "ОБЕРІТЬ ОПЦІЮ")
            choice = self.get_choice(options)
            
            if choice == "0":
                break
            
            handler = handlers.get(choice)
            if handler:
                try:
                    await handler()
                except Exception as e:
                    print(f"\n  Помилка: {e}")
                
                self.wait()


# Функції для backward compatibility
async def send_vmd_report_email(date_from: str, date_to: str, report_title: str) -> bool:
    """Відправляє email зі звітом (backward compatibility)"""
    menu = MailingMenu()
    return await menu.send_vmd_report_email(date_from, date_to, report_title)


async def show_mailing_menu():
    """Меню розсилки (backward compatibility)"""
    menu = MailingMenu()
    await menu.run()
