#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IMAP утиліти для VMD Extractor
"""

import imaplib
import email
from datetime import date, timedelta
from typing import Optional, Dict
from email.utils import parsedate_to_datetime

from ..config import (
    IMAP_HOST,
    IMAP_PORT,
    IMAP_USER,
    IMAP_PASS,
    ALLOWED_SENDERS,
    MIN_SIZE_KB,
    MAX_SIZE_KB,
    LOCAL_TZ,
)
from .helpers import decode_str


def connect_imap() -> Optional[imaplib.IMAP4_SSL]:
    """
    Підключення до IMAP сервера.
    """
    try:
        imap_conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        imap_conn.login(IMAP_USER, IMAP_PASS)
        return imap_conn
    except Exception as e:
        print(f"Помилка підключення до IMAP: {e}")
        return None


def format_imap_date(d: date) -> str:
    """
    Форматування дати для IMAP search (DD-MMM-YYYY)
    """
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    return f"{d.day:02d}-{months[d.month-1]}-{d.year}"


def build_imap_search_criteria(date_from: Optional[date] = None,
                               date_to: Optional[date] = None) -> str:
    """
    Побудова IMAP search criteria для фільтрації по даті.
    """
    criteria = []

    if date_from:
        criteria.append(f"SENTSINCE {format_imap_date(date_from)}")

    if date_to:
        date_to_exclusive = date_to + timedelta(days=1)
        criteria.append(f"SENTBEFORE {format_imap_date(date_to_exclusive)}")

    return " ".join(criteria) if criteria else "ALL"


def parse_email_date(msg) -> Optional[date]:
    """
    Витягує дату з email повідомлення.
    """
    try:
        date_str = msg.get("Date")
        if not date_str:
            return None
        dt = parsedate_to_datetime(date_str)
        return dt.date()
    except Exception:
        return None


def check_is_vmd_attachment(msg) -> bool:
    """
    Перевіряє чи містить повідомлення ВМД вкладення.
    Використовується там, де потрібне повне повідомлення.
    """
    try:
        mail_from = decode_str(msg.get("From", ""))
        mail_from_lower = mail_from.lower()

        sender_allowed = any(s in mail_from_lower for s in ALLOWED_SENDERS)
        if not sender_allowed:
            return False

        for part in msg.walk():
            if part.is_multipart():
                continue

            content_disposition = part.get_content_disposition()
            filename = decode_str(part.get_filename() or "")

            is_attachment = (
                content_disposition == "attachment" or
                (filename and filename.lower().endswith(".imfx"))
            )

            if not is_attachment:
                continue

            try:
                payload = part.get_payload(decode=True) or b""
                if not payload:
                    continue
            except Exception:
                continue

            size_kb = len(payload) / 1024.0
            if MIN_SIZE_KB <= size_kb <= MAX_SIZE_KB:
                return True

        return False
    except Exception:
        return False


def check_vmd_attachment_lightweight(
    imap_conn: imaplib.IMAP4_SSL,
    msg_num: bytes,
    folder_name: str,
    need_payload: bool = False,
    use_uid: bool = False,
) -> Optional[Dict]:
    """
    Швидка перевірка чи містить повідомлення ВМД вкладення.
    Використовує тільки потрібні частини повідомлення, щоб зменшити навантаження.

    Returns:
        Dict з інформацією про вкладення або None.
        Якщо need_payload=False, повертає тільки метадані (без payload).
    """
    try:
        # Перевіряємо відправника (тільки FROM)
        if use_uid:
            typ, data = imap_conn.uid("fetch", msg_num, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
        else:
            typ, data = imap_conn.fetch(msg_num, "(BODY.PEEK[HEADER.FIELDS (FROM)])")
        if typ != "OK" or not data or not data[0]:
            return None

        header_bytes = data[0][1]
        if not isinstance(header_bytes, bytes):
            return None

        header_str = header_bytes.decode("utf-8", errors="ignore")
        msg_header = email.message_from_string(header_str)
        mail_from = decode_str(msg_header.get("From", ""))
        mail_from_lower = mail_from.lower()

        sender_allowed = any(s in mail_from_lower for s in ALLOWED_SENDERS)
        if not sender_allowed:
            return None

        # Отримуємо все тіло (PEEK, щоб не позначати як прочитане)
        if use_uid:
            typ, msg_data = imap_conn.uid("fetch", msg_num, "(BODY.PEEK[])")
        else:
            typ, msg_data = imap_conn.fetch(msg_num, "(BODY.PEEK[])")
        if typ != "OK" or not msg_data:
            return None

        raw = msg_data[0][1]
        if not isinstance(raw, bytes):
            return None

        msg = email.message_from_bytes(raw)
        subject = decode_str(msg.get("Subject", ""))
        message_id = msg.get("Message-ID")
        sent_at = None
        msg_date = msg.get("Date")
        if msg_date:
            try:
                dt = parsedate_to_datetime(msg_date)
                if dt.tzinfo:
                    dt = dt.astimezone(LOCAL_TZ)
                else:
                    dt = dt.replace(tzinfo=LOCAL_TZ)
                sent_at = dt.isoformat()
            except Exception:
                sent_at = None

        message_uid = msg_num.decode() if isinstance(msg_num, bytes) else str(msg_num)

        for part in msg.walk():
            if part.is_multipart():
                continue

            content_disposition = part.get_content_disposition()
            filename = decode_str(part.get_filename() or "")

            is_attachment = (
                content_disposition == "attachment" or
                (filename and filename.lower().endswith(".imfx"))
            )

            if not is_attachment:
                continue

            try:
                payload = part.get_payload(decode=True) or b""
                if not payload:
                    continue
            except Exception:
                continue

            size_kb = len(payload) / 1024.0
            if not (MIN_SIZE_KB <= size_kb <= MAX_SIZE_KB):
                continue

            base_payload = {
                "source": mail_from,
                "msg_num": msg_num,
                "folder_name": folder_name,
                "filename": filename,
                "size_kb": size_kb,
                "subject": subject,
                "message_id": message_id,
                "sent_at": sent_at,
                "message_uid": message_uid,
            }

            if need_payload:
                base_payload["payload"] = payload
                return base_payload
            return base_payload

        return None

    except Exception:
        return None


