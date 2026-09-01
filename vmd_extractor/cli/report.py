#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для звіту про кількість ВМД за вказаний діапазон дат
"""

import imaplib
import email
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict
import concurrent.futures
import threading

# Додаємо поточну директорію до шляху
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from vmd_extractor.utils.imap_utils import (
    connect_imap,
    format_imap_date,
    build_imap_search_criteria,
    parse_email_date,
    check_is_vmd_attachment,
    check_vmd_attachment_lightweight
)
from vmd_extractor.utils.helpers import decode_str


def _process_message_with_connection(
    imap_conn: imaplib.IMAP4_SSL,
    folder_name: str,
    msg_num: bytes,
    *,
    use_uid: bool = False,
) -> Optional[tuple]:
    """
    Обробляє повідомлення, використовуючи вже відкритий IMAP конекшен.
    Повертає (дата, UID, folder_name) якщо знайдено валідну ВМД.
    """
    try:
        attachment_info = check_vmd_attachment_lightweight(
            imap_conn, msg_num, folder_name, need_payload=False, use_uid=use_uid
        )
        if not attachment_info:
            return None

        if use_uid:
            typ, date_data = imap_conn.uid("fetch", msg_num, "(BODY.PEEK[HEADER.FIELDS (DATE)])")
        else:
            typ, date_data = imap_conn.fetch(msg_num, "(BODY.PEEK[HEADER.FIELDS (DATE)])")
        msg_date = date.today()

        if typ == "OK" and date_data and date_data[0]:
            try:
                header_bytes = date_data[0][1]
                if isinstance(header_bytes, bytes):
                    header_str = header_bytes.decode('utf-8', errors='ignore')
                    msg_header = email.message_from_string(header_str)
                    parsed_date = parse_email_date(msg_header)
                    if parsed_date:
                        msg_date = parsed_date
            except Exception:
                pass

        msg_identifier = msg_num.decode() if isinstance(msg_num, bytes) else str(msg_num)
        return (msg_date, msg_identifier, folder_name)
    except Exception:
        return None


def process_message_batch(
    folder_name: str,
    msg_nums: List[bytes],
    num_threads: int = 5,
    *,
    verbose: bool = True,
    show_progress: bool = False,
    use_uid: bool = False,
) -> tuple:
    """
    Асинхронна обробка повідомлень з використанням кількох потоків.
    Кожен потік має своє IMAP з'єднання.
    Повертає (vmd_by_date, vmd_uids) де:
    - vmd_by_date: Dict[date, int] - кількість ВМД по датах
    - vmd_uids: List[tuple] - список (folder_name, msg_num) для ВМД
    """
    vmd_by_date = defaultdict(int)
    vmd_uids = []
    total = len(msg_nums)
    processed = 0
    lock = threading.Lock()
    
    def process_chunk(chunk: List[bytes]):
        """Обробка частини повідомлень в одному потоці"""
        nonlocal processed
        chunk_results = []
        imap_conn = None
        
        try:
            imap_conn = connect_imap()
            if not imap_conn:
                return []
            typ, _ = imap_conn.select(folder_name, readonly=True)
            if typ != "OK":
                return []

            for msg_num in chunk:
                msg_identifier = msg_num.decode() if isinstance(msg_num, bytes) else msg_num
                result = _process_message_with_connection(
                    imap_conn, folder_name, msg_identifier, use_uid=use_uid
                )
                if result:
                    chunk_results.append(result)
                
                with lock:
                    processed += 1
                    if show_progress:
                        # Показуємо прогрес у форматі [X/Y] для кожного повідомлення
                        print(f"   [{processed}/{total}]", end='\r')
                    elif verbose and (processed % 5 == 0 or processed == total):
                        percent = (processed / total) * 100
                        print(f"  Обробка: {processed}/{total} ({percent:.1f}%)", end='\r')
        finally:
            if imap_conn:
                try:
                    imap_conn.logout()
                except Exception:
                    pass
        
        return chunk_results
    
    # Розділяємо повідомлення на частини для кожного потоку
    chunk_size = max(1, total // num_threads)
    chunks = [msg_nums[i:i + chunk_size] for i in range(0, total, chunk_size)]
    
    # Обробляємо паралельно
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = []
        for chunk in chunks:
            future = executor.submit(process_chunk, chunk)
            futures.append(future)
        
        # Збираємо результати
        for future in concurrent.futures.as_completed(futures):
            try:
                chunk_results = future.result()
                for result in chunk_results:
                    msg_date, msg_num, folder = result
                    vmd_by_date[msg_date] += 1
                    vmd_uids.append((folder, msg_num))
            except Exception:
                continue
    
    if verbose or show_progress:
        print()  # Новий рядок після прогресу
    return vmd_by_date, vmd_uids


def scan_folder_for_vmd(
    imap_conn: imaplib.IMAP4_SSL,
    folder_name: str,
    date_from: Optional[date],
    date_to: Optional[date],
    *,
    verbose: bool = True,
    folder_label: Optional[str] = None,
    show_details: bool = False,
    show_progress: bool = False,
) -> tuple:
    """
    Сканує папку на наявність ВМД за вказаний діапазон дат.
    Використовує паралельну обробку в кількох потоках для швидкості.
    Повертає (vmd_by_date, vmd_uids) де:
    - vmd_by_date: Dict[date, int] - кількість ВМД по датах
    - vmd_uids: List[tuple] - список (folder_name, msg_num) для ВМД
    """
    label = folder_label or folder_name

    try:
        # Вибір папки
        typ, data = imap_conn.select(folder_name, readonly=True)
        if typ != "OK":
            if verbose and show_details:
                print(f"  Не вдалося вибрати папку '{label}'")
            return defaultdict(int), []
        
        # Формуємо search criteria
        search_criteria = build_imap_search_criteria(date_from, date_to)
        
        # Отримуємо список повідомлень
        typ, data = imap_conn.uid("search", None, search_criteria)
        if typ != "OK" or not data or not data[0]:
            if verbose and show_details:
                print("  Повідомлення за критеріями не знайдено.")
            return defaultdict(int), []
        
        msg_nums = data[0].split()
        
        if not msg_nums:
            return defaultdict(int), []
        
        # Закриваємо з'єднання перед паралельною обробкою
        # (кожен потік створить своє з'єднання)
        try:
            imap_conn.logout()
        except Exception:
            pass
        
        # Обробляємо паралельно з кількома потоками
        # verbose=True тільки для show_details (детальний режим)
        # show_progress показує прогрес у форматі [X/Y]
        vmd_by_date, vmd_uids = process_message_batch(
            folder_name,
            msg_nums,
            num_threads=5,
            verbose=verbose and show_details,
            show_progress=show_progress,
            use_uid=True,
        )
        
        if verbose and show_details and vmd_uids:
            print(f"  Знайдено ВМД: {len(vmd_uids)}")
        
        return vmd_by_date, vmd_uids
        
    except Exception as e:
        if verbose and show_details:
            print(f"  Помилка сканування папки '{label}': {e}")
        return defaultdict(int), []


def get_vmd_count_report(date_from: Optional[date], date_to: Optional[date], 
                        show_details: bool = True, show_progress: bool = False) -> tuple:
    """
    Отримує звіт про кількість ВМД за вказаний діапазон дат.
    Повертає (vmd_by_date, vmd_uids) де:
    - vmd_by_date: Dict[date, int] - кількість ВМД по датах
    - vmd_uids: List[tuple] - список (folder_name, msg_num) для ВМД
    
    Args:
        date_from: Початкова дата
        date_to: Кінцева дата
        show_details: Показувати детальний звіт в консоль
    """
    if show_details:
        print("="*60)
        print("ЗВІТ ПРО НАЯВНІСТЬ ВМД НА ПОШТІ")
        print("="*60)
        
        if date_from or date_to:
            date_range = []
            if date_from:
                date_range.append(f"від {date_from.strftime('%Y-%m-%d')}")
            if date_to:
                date_range.append(f"до {date_to.strftime('%Y-%m-%d')}")
            print(f"Діапазон: {' '.join(date_range)}")
        else:
            print("Діапазон: всі доступні ВМД")
        
        print("="*60)
    
    # Підключення до IMAP (тільки для пошуку повідомлень)
    imap_conn = connect_imap()
    if not imap_conn:
        if show_details:
            print("Не вдалося підключитися до пошти")
        return defaultdict(int), []
    
    try:
        folders_to_search = [
            ("INBOX", "Вхідні"),
            ("&BB8EQAQ+BEcEOARCBDAEPQRW-", "Прочитані"),
        ]
        
        # Збираємо дані з усіх папок
        all_vmd_by_date = defaultdict(int)
        all_vmd_uids = []
        total_folders = len(folders_to_search)
        
        for folder_idx, (folder_name, folder_label) in enumerate(folders_to_search, 1):
            if show_details:
                print(f"\nПапка: {folder_label}")
            
            vmd_by_date, vmd_uids = scan_folder_for_vmd(
                imap_conn,
                folder_name,
                date_from,
                date_to,
                verbose=show_details or show_progress,
                folder_label=folder_label,
                show_details=show_details,
                show_progress=show_progress and not show_details,
            )
            
            # Об'єднуємо результати
            for msg_date, count in vmd_by_date.items():
                all_vmd_by_date[msg_date] += count
            all_vmd_uids.extend(vmd_uids)
            
            if show_progress and not show_details:
                current_total = len(all_vmd_uids)
                print(f"   ВМД: [{current_total}]", end='\r')
            
            # Після обробки папки, з'єднання вже закрите в scan_folder_for_vmd
            # Створюємо нове для наступної папки (якщо є ще папки)
            if (folder_name, folder_label) != folders_to_search[-1]:
                try:
                    imap_conn.logout()
                except Exception:
                    pass
                imap_conn = connect_imap()
                if not imap_conn:
                    if show_details:
                        print("Не вдалося переподключитися до пошти")
                    break
        
        # Показуємо фінальний результат
        if show_progress and not show_details:
            total_found = len(all_vmd_uids)
            print(f"   ВМД: [{total_found}]")
        
        # Виводимо звіт
        if show_details:
            print("\n" + "="*60)
            print("ПІДСУМОК")
            print("="*60)
            
            if not all_vmd_by_date:
                print("ВМД не знайдено за вказаний діапазон дат")
            else:
                # Сортуємо по даті
                sorted_dates = sorted(all_vmd_by_date.keys())
                total_count = sum(all_vmd_by_date.values())
                
                print(f"  Загальна кількість ВМД: {total_count}")
                print(f"  Днів з ВМД: {len(sorted_dates)}")
                print("  Розподіл за датами:")
                
                for msg_date in sorted_dates:
                    count = all_vmd_by_date[msg_date]
                    print(f"    - {msg_date.strftime('%Y-%m-%d')}: {count}")
                
                print(f"\n  Всього: {total_count} ВМД")
            
            print("="*60)
        
        return all_vmd_by_date, all_vmd_uids
        
    finally:
        try:
            imap_conn.logout()
        except Exception:
            pass


def generate_report(date_from: Optional[date], date_to: Optional[date]) -> None:
    """Генерує звіт про кількість ВМД за вказаний діапазон дат (для CLI)"""
    vmd_report, vmd_uids = get_vmd_count_report(date_from, date_to, show_details=True)
    # UID не використовуються в CLI режимі, тільки для інтеграції


def main():
    """Головна функція"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Звіт про наявність ВМД на пошті за вказаний діапазон дат",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Приклади використання:

  # Звіт за останні 7 днів
  python -m vmd_extractor.cli.report --days 7

  # Звіт за конкретний діапазон
  python -m vmd_extractor.cli.report --from 2025-01-01 --to 2025-01-31

  # Звіт за поточний день
  python -m vmd_extractor.cli.report --today

  # Звіт за всі доступні ВМД
  python -m vmd_extractor.cli.report
        """
    )
    
    def parse_date(date_str: str) -> date:
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Невірний формат дати: {date_str}. Використовуйте YYYY-MM-DD")
    
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument("--today", action="store_true", help="Звіт за поточний день")
    date_group.add_argument("--days", type=int, metavar="N", help="Звіт за останні N днів")
    date_group.add_argument("--from", dest="date_from", type=parse_date, metavar="YYYY-MM-DD", 
                           help="Початкова дата (включно)")
    parser.add_argument("--to", dest="date_to", type=parse_date, metavar="YYYY-MM-DD", 
                       help="Кінцева дата (включно)")
    
    args = parser.parse_args()
    
    # Визначаємо дати
    date_from = None
    date_to = None
    
    if args.today:
        today = date.today()
        date_from = today
        date_to = today
    elif args.days:
        date_from = date.today() - timedelta(days=args.days)
        date_to = date.today()
    else:
        date_from = args.date_from
        date_to = args.date_to
    
    generate_report(date_from, date_to)


if __name__ == "__main__":
    main()


