#!/usr/bin/env python3
"""
Утиліта для швидкого зчитування міток (labels) з Trello.

Використання:
    python scripts/list_trello_labels.py --card-id 691dc89ce2565e32d845170b

Скрипт читає вказану картку, виводить таблицю з мітками
та допомагає перенести інформацію в документацію.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from textwrap import dedent
from typing import List, Optional

# Гарантуємо, що корінь проекту у sys.path навіть при запуску зі scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from vmd_extractor.config import (  # noqa: E402
    TRELLO_API_KEY,
    TRELLO_API_TOKEN,
    TRELLO_BOARD_ID,
    TRELLO_LIST_ID,
    TRELLO_LABEL_CARD_ID,
)
from vmd_extractor.utils.trello_integration import TrelloIntegration  # noqa: E402


def _read_env(name: str, fallback: Optional[str]) -> Optional[str]:
    """Повертає значення змінної середовища з запасним варіантом."""
    return os.getenv(name, fallback) or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Вивести список усіх міток, привʼязаних до картки Trello."
    )
    parser.add_argument(
        "--card-id",
        default=os.getenv("TRELLO_LABEL_CARD_ID", TRELLO_LABEL_CARD_ID),
        help="ID картки Trello з усіма мітками (можна задати через TRELLO_LABEL_CARD_ID).",
    )
    return parser


async def fetch_labels(card_id: str) -> List[dict]:
    """Отримує список міток для картки."""
    api_key = _read_env("TRELLO_API_KEY", TRELLO_API_KEY)
    api_token = _read_env("TRELLO_API_TOKEN", TRELLO_API_TOKEN)
    board_id = _read_env("TRELLO_BOARD_ID", TRELLO_BOARD_ID)
    list_id = _read_env("TRELLO_LIST_ID", TRELLO_LIST_ID)

    missing = [name for name, value in [
        ("TRELLO_API_KEY", api_key),
        ("TRELLO_API_TOKEN", api_token),
        ("TRELLO_BOARD_ID", board_id),
        ("TRELLO_LIST_ID", list_id),
    ] if not value]

    if missing:
        raise RuntimeError(
            "Не вистачає налаштувань Trello: " + ", ".join(missing)
        )

    trello = TrelloIntegration(
        api_key=api_key,
        api_token=api_token,
        board_id=board_id,
        list_id=list_id,
        enabled=True,
    )

    card_info = await trello.get_card_info(card_id)
    if not card_info:
        raise RuntimeError(f"Не вдалося отримати дані картки {card_id}")

    labels = card_info.get("labels") or []
    return labels


def print_labels(labels: List[dict]) -> None:
    """Виводить акуратну таблицю з мітками."""
    if not labels:
        print("Міток не знайдено. Перевірте, що картка містить усі потрібні labels.")
        return

    header = f"{'Назва':30} | {'Колір':12} | {'ID':24}"
    separator = "-" * len(header)
    print(separator)
    print(header)
    print(separator)
    for label in labels:
        name = (label.get("name") or "").strip() or "<без назви>"
        color = label.get("color") or "none"
        label_id = label.get("id") or "—"
        print(f"{name:30} | {color:12} | {label_id}")
    print(separator)
    print("\nСкопіюйте цю таблицю у README.md (розділ “Мітки Trello”).")


async def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        labels = await fetch_labels(args.card_id)
    except Exception as exc:  # noqa: BLE001 - показуємо користувачу причину
        print(f"Помилка отримання міток: {exc}")
        return 2

    print_labels(labels)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

