#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для перегляду всіх кастомних полів Trello дошки
"""

import asyncio
import sys
from pathlib import Path

# Додаємо корінь проекту до шляху
project_root = Path(__file__).parent.parent  # scripts -> корінь проекту
sys.path.insert(0, str(project_root))

from vmd_extractor.config import TRELLO_API_KEY, TRELLO_API_TOKEN, TRELLO_BOARD_ID, TRELLO_LIST_ID
from vmd_extractor.utils.trello_integration import TrelloIntegration


async def view_custom_fields():
    """Виводить всі кастомні поля з Trello дошки"""
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN or not TRELLO_BOARD_ID:
        print("❌ Помилка: Не налаштовані Trello API ключі або Board ID")
        print("Перевірте файл vmd_extractor/config.py")
        return
    
    print("=" * 80)
    print("ПЕРЕГЛЯД КАСТОМНИХ ПОЛІВ TRELLO")
    print("=" * 80)
    print(f"Board ID: {TRELLO_BOARD_ID}")
    print()
    
    # list_id потрібен для ініціалізації, але не використовується для отримання кастомних полів
    trello = TrelloIntegration(
        api_key=TRELLO_API_KEY,
        api_token=TRELLO_API_TOKEN,
        board_id=TRELLO_BOARD_ID,
        list_id=TRELLO_LIST_ID or "dummy_list_id"  # Можна передати будь-який ID, не використовується
    )
    
    print("Отримання кастомних полів з дошки...")
    custom_fields = await trello.get_board_custom_fields()
    
    if not custom_fields:
        print("\n⚠️  Кастомні поля не знайдено або дошка не має кастомних полів")
        print("\nПримітка: Кастомні поля доступні тільки в Trello Premium")
        return
    
    print(f"\n✅ Знайдено кастомних полів: {len(custom_fields)}\n")
    print("=" * 80)
    
    for idx, field in enumerate(custom_fields, 1):
        field_id = field.get("id", "N/A")
        field_name = field.get("name", "Без назви")
        field_type = field.get("type", "unknown")
        
        print(f"\n{idx}. {field_name}")
        print(f"   ID: {field_id}")
        print(f"   Тип: {field_type}")
        
        # Додаткова інформація залежно від типу
        if field_type == "list":
            options = field.get("options", [])
            if options:
                print(f"   Опції ({len(options)}):")
                for opt_idx, option in enumerate(options[:10], 1):  # Показуємо перші 10
                    opt_name = option.get("value", {}).get("text", "Без назви")
                    opt_id = option.get("id", "N/A")
                    print(f"      {opt_idx}. {opt_name} (ID: {opt_id})")
                if len(options) > 10:
                    print(f"      ... та ще {len(options) - 10} опцій")
        
        # Показуємо позицію поля (якщо є)
        pos = field.get("pos")
        if pos is not None:
            print(f"   Позиція: {pos}")
    
    print("\n" + "=" * 80)
    print(f"Всього полів: {len(custom_fields)}")
    print("=" * 80)


if __name__ == "__main__":
    try:
        asyncio.run(view_custom_fields())
    except KeyboardInterrupt:
        print("\n\n⚠️  Перервано користувачем")
    except Exception as e:
        print(f"\n❌ Помилка: {e}")
        import traceback
        traceback.print_exc()

