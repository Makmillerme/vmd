#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль управління Trello мітками.
"""

import asyncio
import logging
import sqlite3
from collections import defaultdict

from vmd_extractor.config import (
    DB_PATH, TRELLO_ENABLED, TRELLO_API_KEY, TRELLO_API_TOKEN,
    TRELLO_BOARD_ID, TRELLO_LIST_ID, get_trello_label_for_vehicle_type_async
)
from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.utils.trello_integration import TrelloIntegration
from vmd_extractor.utils.helpers import normalize_vehicle_type
from vmd_extractor.utils.data_extractor import fix_vehicle_type_typos
from ..utils import print_header, print_menu, get_user_choice, wait_for_enter

logger = logging.getLogger(__name__)


async def show_trello_labels_menu():
    """Меню управління мітками Trello"""
    print_header("УПРАВЛІННЯ МІТКАМИ TRELLO")
    
    if not TRELLO_ENABLED:
        print("  Trello інтеграція вимкнена.")
        print("  Увімкніть її в .env файлі (TRELLO_ENABLED=true)")
        input("\nНатисніть Enter для продовження...")
        return
    
    options = {
        "1": "Створити мітки для типів авто",
        "2": "Показати всі мітки в БД",
        "3": "Перевірити дублікати типів авто",
        "4": "Виправити регістр типів авто",
        "5": "Виправити помилки у типах авто",
        "6": "Оновити кольори міток на sky",
        "7": "Видалити всі мітки з карток",
        "8": "Синхронізувати мітки на всіх картках",
        "0": "Повернутися до меню Trello"
    }
    
    print_menu(options, "ОБЕРІТЬ ОПЦІЮ")
    choice = get_user_choice(options)
    
    if choice == "0":
        return
    elif choice == "1":
        await create_trello_labels()
    elif choice == "2":
        await show_trello_labels_list()
    elif choice == "3":
        await check_vehicle_type_duplicates()
    elif choice == "4":
        await fix_vehicle_type_case()
    elif choice == "5":
        await fix_vehicle_type_typos_in_db()
    elif choice == "6":
        await update_label_colors_to_sky()
    elif choice == "7":
        await remove_all_labels_from_cards()
    elif choice == "8":
        await sync_labels_on_all_cards()


async def create_trello_labels():
    """Створює мітки Trello для типів авто, які не мають міток"""
    print_header("СТВОРЕННЯ МІТОК TRELLO")
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN or not TRELLO_BOARD_ID:
        print("  ❌ Не налаштовані Trello API credentials")
        print("     Потрібні: TRELLO_API_KEY, TRELLO_API_TOKEN, TRELLO_BOARD_ID")
        input("\nНатисніть Enter для продовження...")
        return
    
    try:
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        # Отримуємо типи авто без міток
        types_without_labels = await db.get_vehicle_types_without_labels()
        
        # Нормалізація: "Тентований" (тип кузова у ВМД) = мітка "Тентована платформа"
        types_to_create = []
        seen = set()
        for vt in types_without_labels:
            norm = "Тентована платформа" if (vt or "").strip().lower() == "тентований" else (vt or "").strip()
            if not norm or norm.lower() in seen:
                continue
            seen.add(norm.lower())
            # Не додаємо, якщо мітка для цього типу вже є (після нормалізації)
            if await db.get_trello_label_id(norm):
                continue
            types_to_create.append(norm)
        
        if not types_to_create:
            print("  ✅ Всі типи авто вже мають мітки Trello")
            wait_for_enter()
            return
        
        print(f"\n  📋 Знайдено {len(types_to_create)} типів авто без міток:")
        for i, vtype in enumerate(types_to_create, 1):
            print(f"     {i}. {vtype}")
        
        confirm = input("\n  Створити мітки для цих типів? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("  Операцію скасовано.")
            wait_for_enter()
            return
        
        # Підключаємося до Trello
        trello = TrelloIntegration(
            api_key=TRELLO_API_KEY,
            api_token=TRELLO_API_TOKEN,
            board_id=TRELLO_BOARD_ID,
            list_id="",
            enabled=True,
        )
        
        # Використовуємо один колір для всіх міток - блакитний (sky)
        LABEL_COLOR = "sky"
        
        print(f"\n  🎨 Всі мітки будуть створені з кольором: {LABEL_COLOR} (блакитний)")
        
        created_count = 0
        error_count = 0
        
        print("\n  🔨 Створення міток...")
        print("-" * 80)
        
        for idx, vehicle_type in enumerate(types_to_create, 1):
            print(f"  [{idx}/{len(types_to_create)}] {vehicle_type} (колір: {LABEL_COLOR})")
            
            # Створюємо мітку в Trello з блакитним кольором
            label_data = await trello.create_label(name=vehicle_type, color=LABEL_COLOR)
            
            if label_data:
                # Зберігаємо в БД
                await db.save_trello_label(
                    vehicle_type=vehicle_type,
                    trello_label_id=label_data["id"],
                    label_name=label_data["name"],
                    label_color=label_data["color"],
                )
                created_count += 1
                print(f"     ✅ Створено: ID {label_data['id']}")
            else:
                error_count += 1
                print(f"     ❌ Помилка створення")
            
            await asyncio.sleep(0.5)
        
        print("\n" + "=" * 80)
        print(f"  📊 РЕЗУЛЬТАТИ:")
        print(f"     Створено міток: {created_count}")
        print(f"     Помилок: {error_count}")
        print(f"     Всього оброблено: {len(types_to_create)}")
        print("=" * 80)
        
        if created_count > 0:
            print("\n  ✅ Мітки успішно створені та збережені в БД!")
            print("     Тепер вони будуть автоматично використовуватися для нових карток.")
        
    except Exception as e:
        print(f"\n  ❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНатисніть Enter для продовження...")


async def show_trello_labels_list():
    """Показує всі мітки Trello з БД з перевіркою кольорів"""
    print_header("МІТКИ TRELLO В БД")
    
    try:
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        labels = await db.get_all_trello_labels()
        
        if not labels:
            print("  Міток в БД не знайдено.")
            wait_for_enter()
            return
        
        print(f"\n  Знайдено {len(labels)} міток:\n")
        print(f"  {'Статус':<4} {'Тип авто':<46} | {'ID мітки':<30} | {'Колір':<15}")
        print("  " + "-" * 100)
        
        wrong_color_count = 0
        for label in labels:
            vtype = label.get("vehicle_type", "N/A")
            label_id = label.get("trello_label_id", "N/A")
            color = label.get("label_color", "N/A")
            
            # Перевіряємо чи колір правильний
            if color and color != "sky":
                status = "⚠️"
                wrong_color_count += 1
            else:
                status = "✅"
            
            print(f"  {status} {vtype:<46} | {label_id:<30} | {color:<15}")
        
        print("  " + "-" * 100)
        
        if wrong_color_count > 0:
            print(f"\n  ⚠️ Знайдено {wrong_color_count} міток з неправильним кольором (не sky)")
            print("     Рекомендація: запустіть опцію '5. Оновити кольори міток на sky'")
        else:
            print("\n  ✅ Всі мітки мають правильний колір (sky)")
        
    except Exception as e:
        print(f"\n  ❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНатисніть Enter для продовження...")


async def check_vehicle_type_duplicates():
    """Перевіряє дублікати типів авто з різним регістром"""
    print_header("ПЕРЕВІРКА ДУБЛІКАТІВ ТИПІВ АВТО")
    
    try:
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Отримуємо всі типи авто - використовуємо нормалізовану колонку
        cursor.execute("""
            SELECT 
                vehicle_type,
                COUNT(*) as count
            FROM vehicles
            WHERE vehicle_type IS NOT NULL
              AND TRIM(vehicle_type) != ''
            GROUP BY vehicle_type
            ORDER BY vehicle_type
        """)
        
        rows = cursor.fetchall()
        
        # Групуємо по нормалізованому типу
        normalized_groups = defaultdict(list)
        for row in rows:
            vtype = row["vehicle_type"]
            count = row["count"]
            normalized = vtype.strip().lower()
            normalized_groups[normalized].append({
                "original": vtype,
                "count": count
            })
        
        # Знаходимо дублікати
        duplicates = {k: v for k, v in normalized_groups.items() if len(v) > 1}
        
        if duplicates:
            print(f"\n  ⚠️ Знайдено {len(duplicates)} дублікатів типів авто з різним регістром:\n")
            
            for normalized, variants in duplicates.items():
                print(f"  '{normalized}' (нормалізований):")
                total_count = 0
                for variant in variants:
                    print(f"    - '{variant['original']}': {variant['count']} записів")
                    total_count += variant['count']
                print(f"    Всього: {total_count} записів")
                print()
            
            print("  💡 Рекомендація: Запустіть опцію '4. Виправити регістр типів авто'")
        else:
            print("\n  ✅ Дублікатів не знайдено - всі типи мають правильний регістр")
        
        conn.close()
        
    except Exception as e:
        print(f"\n  ❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНатисніть Enter для продовження...")


async def fix_vehicle_type_case():
    """Виправляє регістр типів авто в БД"""
    print_header("ВИПРАВЛЕННЯ РЕГІСТРУ ТИПІВ АВТО")
    
    try:
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Знаходимо всі типи з різним регістром - використовуємо нормалізовану колонку
        cursor.execute("""
            SELECT 
                id,
                vehicle_type
            FROM vehicles
            WHERE vehicle_type IS NOT NULL
              AND TRIM(vehicle_type) != ''
        """)
        
        rows = cursor.fetchall()
        
        # Групуємо по нормалізованому типу
        normalized_groups = defaultdict(list)
        for row in rows:
            vtype = row["vehicle_type"]
            normalized = normalize_vehicle_type(vtype)
            if vtype != normalized:
                normalized_groups[normalized].append({
                    "id": row["id"],
                    "original": vtype,
                })
        
        if not normalized_groups:
            print("\n  ✅ Всі типи авто вже мають правильний регістр")
            conn.close()
            wait_for_enter()
            return
        
        print(f"\n  📋 Знайдено {len(normalized_groups)} типів авто, які потребують виправлення:")
        total_to_fix = sum(len(v) for v in normalized_groups.values())
        print(f"     Всього записів для виправлення: {total_to_fix}\n")
        
        for normalized_type, variants in list(normalized_groups.items())[:5]:
            print(f"  '{normalized_type}': {len(variants)} записів")
        if len(normalized_groups) > 5:
            print(f"  ... та ще {len(normalized_groups) - 5} типів")
        
        confirm = input("\n  Виправити регістр типів авто? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("  Операцію скасовано.")
            conn.close()
            wait_for_enter()
            return
        
        total_fixed = 0
        
        for normalized_type, variants in normalized_groups.items():
            for variant in variants:
                try:
                    # Оновлюємо нормалізовану колонку vehicle_type
                    cursor.execute(
                        "UPDATE vehicles SET vehicle_type = ? WHERE id = ?",
                        (normalized_type, variant["id"])
                    )
                    total_fixed += 1
                except Exception as e:
                    print(f"    ⚠️ Помилка оновлення ID {variant['id']}: {e}")
        
        # Виправляємо дублікати міток
        cursor.execute("SELECT vehicle_type, trello_label_id FROM trello_labels")
        label_rows = cursor.fetchall()
        
        label_groups = defaultdict(list)
        for row in label_rows:
            vtype = row["vehicle_type"]
            normalized = normalize_vehicle_type(vtype)
            label_groups[normalized].append({
                "original": vtype,
                "label_id": row["trello_label_id"]
            })
        
        duplicates = {k: v for k, v in label_groups.items() if len(v) > 1}
        labels_fixed = 0
        
        if duplicates:
            for normalized_type, variants in duplicates.items():
                # Використовуємо перший варіант з великої літери
                correct_variant = None
                for variant in variants:
                    if variant["original"][0].isupper():
                        correct_variant = variant
                        break
                
                if not correct_variant:
                    correct_variant = variants[0]
                
                # Видаляємо інші варіанти
                for variant in variants:
                    if variant != correct_variant:
                        cursor.execute(
                            "DELETE FROM trello_labels WHERE vehicle_type = ?",
                            (variant["original"],)
                        )
                        labels_fixed += 1
                
                # Оновлюємо vehicle_type на нормалізований
                if correct_variant["original"] != normalized_type:
                    cursor.execute(
                        "UPDATE trello_labels SET vehicle_type = ? WHERE trello_label_id = ?",
                        (normalized_type, correct_variant["label_id"])
                    )
        
        conn.commit()
        conn.close()
        
        print("\n" + "=" * 80)
        print(f"  📊 РЕЗУЛЬТАТИ:")
        print(f"     Виправлено записів у vehicles: {total_fixed}")
        print(f"     Виправлено дублікатів міток: {len(duplicates) if duplicates else 0}")
        print("=" * 80)
        print("\n  ✅ Виправлення завершено!")
        
    except Exception as e:
        print(f"\n  ❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНатисніть Enter для продовження...")


async def fix_vehicle_type_typos_in_db():
    """Виправляє типові помилки в типах авто в БД (наприклад, 'контейнеровіз' → 'контейнеровоз')"""
    print_header("ВИПРАВЛЕННЯ ПОМИЛОК У ТИПАХ АВТО")
    
    try:
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        conn = sqlite3.connect(db.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Знаходимо всі типи авто - використовуємо нормалізовану колонку
        cursor.execute("""
            SELECT 
                id,
                vehicle_type
            FROM vehicles
            WHERE vehicle_type IS NOT NULL
              AND TRIM(vehicle_type) != ''
        """)
        
        rows = cursor.fetchall()
        
        # Знаходимо типи з помилками
        typos_found = []
        for row in rows:
            original_type = row["vehicle_type"]
            fixed_type = fix_vehicle_type_typos(original_type)
            if original_type != fixed_type:
                typos_found.append({
                    "id": row["id"],
                    "original": original_type,
                    "fixed": fixed_type,
                })
        
        if not typos_found:
            print("\n  ✅ Помилок у типах авто не знайдено")
            conn.close()
            wait_for_enter()
            return
        
        # Групуємо по типу помилки
        typos_by_fix = defaultdict(list)
        for typo in typos_found:
            key = f"{typo['original']} → {typo['fixed']}"
            typos_by_fix[key].append(typo)
        
        print(f"\n  📋 Знайдено {len(typos_found)} записів з помилками у типах авто:")
        print(f"     Унікальних типів помилок: {len(typos_by_fix)}\n")
        
        for fix_pattern, variants in list(typos_by_fix.items())[:10]:
            print(f"  {fix_pattern}: {len(variants)} записів")
        if len(typos_by_fix) > 10:
            print(f"  ... та ще {len(typos_by_fix) - 10} типів помилок")
        
        confirm = input("\n  Виправити помилки у типах авто? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("  Операцію скасовано.")
            conn.close()
            wait_for_enter()
            return
        
        total_fixed = 0
        
        for typo in typos_found:
            try:
                # Оновлюємо нормалізовану колонку vehicle_type
                cursor.execute(
                    "UPDATE vehicles SET vehicle_type = ? WHERE id = ?",
                    (typo["fixed"], typo["id"])
                )
                total_fixed += 1
            except Exception as e:
                print(f"    ⚠️ Помилка оновлення ID {typo['id']}: {e}")
        
        # Виправляємо мітки Trello
        cursor.execute("SELECT vehicle_type, trello_label_id FROM trello_labels")
        label_rows = cursor.fetchall()
        
        labels_fixed = 0
        for row in label_rows:
            original_type = row["vehicle_type"]
            fixed_type = fix_vehicle_type_typos(original_type)
            if original_type != fixed_type:
                cursor.execute(
                    "UPDATE trello_labels SET vehicle_type = ? WHERE trello_label_id = ?",
                    (fixed_type, row["trello_label_id"])
                )
                labels_fixed += 1
        
        conn.commit()
        conn.close()
        
        print("\n" + "=" * 80)
        print(f"  📊 РЕЗУЛЬТАТИ:")
        print(f"     Виправлено записів у vehicles: {total_fixed}")
        print(f"     Виправлено міток Trello: {labels_fixed}")
        print("=" * 80)
        print("\n  ✅ Виправлення помилок завершено!")
        
    except Exception as e:
        print(f"\n  ❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНатисніть Enter для продовження...")


async def update_label_colors_to_sky():
    """Оновлює кольори всіх міток в Trello та БД на sky (блакитний)"""
    print_header("ОНОВЛЕННЯ КОЛЬОРІВ МІТОК НА SKY")
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN or not TRELLO_BOARD_ID:
        print("  ❌ Не налаштовані Trello API credentials")
        print("     Потрібні: TRELLO_API_KEY, TRELLO_API_TOKEN, TRELLO_BOARD_ID")
        input("\nНатисніть Enter для продовження...")
        return
    
    try:
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        # Отримуємо всі мітки з БД
        all_labels = await db.get_all_trello_labels()
        
        if not all_labels:
            print("  ⚠️ Не знайдено міток в БД")
            wait_for_enter()
            return
        
        # Знаходимо мітки з неправильним кольором
        labels_to_update = [
            label for label in all_labels 
            if label.get("label_color") and label.get("label_color") != "sky"
        ]
        
        if not labels_to_update:
            print("  ✅ Всі мітки вже мають правильний колір (sky)")
            wait_for_enter()
            return
        
        print(f"\n  📋 Знайдено {len(labels_to_update)} міток з неправильним кольором:")
        for label in labels_to_update:
            vtype = label.get("vehicle_type", "N/A")
            current_color = label.get("label_color", "N/A")
            print(f"     - {vtype}: {current_color} → sky")
        
        confirm = input("\n  Оновити кольори міток на sky? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("  Операцію скасовано.")
            wait_for_enter()
            return
        
        trello = TrelloIntegration(
            api_key=TRELLO_API_KEY,
            api_token=TRELLO_API_TOKEN,
            board_id=TRELLO_BOARD_ID,
            list_id="",
            enabled=True,
        )
        
        updated_count = 0
        error_count = 0
        
        print("\n  🔄 Оновлення кольорів міток...")
        print("-" * 80)
        
        for idx, label in enumerate(labels_to_update, 1):
            label_id = label.get("trello_label_id")
            vehicle_type = label.get("vehicle_type", "N/A")
            
            if not label_id:
                continue
            
            try:
                # Оновлюємо колір в Trello
                success = await trello.update_label_color(label_id, "sky")
                
                if success:
                    # Оновлюємо колір в БД
                    await db.save_trello_label(
                        vehicle_type=vehicle_type,
                        trello_label_id=label_id,
                        label_name=label.get("label_name"),
                        label_color="sky",
                    )
                    updated_count += 1
                    print(f"  [{idx}/{len(labels_to_update)}] ✅ {vehicle_type}: оновлено на sky")
                else:
                    error_count += 1
                    print(f"  [{idx}/{len(labels_to_update)}] ❌ {vehicle_type}: помилка оновлення")
                
                await asyncio.sleep(0.3)  # Невелика затримка
                
            except Exception as e:
                error_count += 1
                logger.error(f"Error updating label {label_id}: {e}")
                print(f"  [{idx}/{len(labels_to_update)}] ❌ {vehicle_type}: помилка - {e}")
        
        print("\n" + "=" * 80)
        print(f"  📊 РЕЗУЛЬТАТИ:")
        print(f"     Оновлено міток: {updated_count}")
        print(f"     Помилок: {error_count}")
        print(f"     Всього оброблено: {len(labels_to_update)}")
        print("=" * 80)
        print("\n  ✅ Оновлення кольорів завершено!")
        print("     Всі мітки тепер мають колір sky (блакитний).")
        
    except Exception as e:
        print(f"\n  ❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНатисніть Enter для продовження...")


async def remove_all_labels_from_cards():
    """Видаляє ВСІ мітки з усіх карток Trello (без додавання нових)"""
    print_header("ВИДАЛЕННЯ ВСІХ МІТОК З КАРТОК TRELLO")
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN or not TRELLO_BOARD_ID:
        print("  ❌ Не налаштовані Trello API credentials")
        print("     Потрібні: TRELLO_API_KEY, TRELLO_API_TOKEN, TRELLO_BOARD_ID")
        input("\nНатисніть Enter для продовження...")
        return
    
    try:
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        # Отримуємо всі правильні мітки з БД
        all_labels = await db.get_all_trello_labels()
        valid_label_ids = {label.get("trello_label_id") for label in all_labels if label.get("trello_label_id")}
        
        if not valid_label_ids:
            print("  ⚠️ Не знайдено міток в БД. Спочатку створіть мітки.")
            wait_for_enter()
            return
        
        # Отримуємо всі картки з БД
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT tc.trello_card_id
                FROM trello_cards tc
                WHERE tc.trello_card_id IS NOT NULL 
                  AND tc.trello_card_id != ''
            """)
            rows = await cursor.fetchall()
        
        if not rows:
            print("  ⚠️ Не знайдено карток для обробки")
            wait_for_enter()
            return
        
        print(f"\n  Знайдено {len(rows)} карток для обробки")
        print("     Будуть видалені ВСІ мітки з усіх карток")
        
        confirm = input("\n  Видалити всі мітки з карток? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("  Операцію скасовано.")
            wait_for_enter()
            return
        
        trello = TrelloIntegration(
            api_key=TRELLO_API_KEY,
            api_token=TRELLO_API_TOKEN,
            board_id=TRELLO_BOARD_ID,
            list_id=TRELLO_LIST_ID,
            enabled=True,
        )
        
        processed_count = 0
        error_count = 0
        removed_labels_count = 0
        
        print("\n  🔄 Видалення міток...")
        print("-" * 80)
        
        for idx, row in enumerate(rows, 1):
            card_id = row["trello_card_id"]
            
            try:
                # Отримуємо поточні мітки на картці
                current_labels = await trello.get_card_labels(card_id)
                current_label_ids = {label.get("id") for label in current_labels if label.get("id")}
                
                # Видаляємо ВСІ мітки
                for label_id in current_label_ids:
                    removed = await trello.remove_label_from_card(card_id, label_id)
                    if removed:
                        removed_labels_count += 1
                    await asyncio.sleep(0.2)  # Невелика затримка
                
                if current_label_ids:
                    processed_count += 1
                
                if idx % 10 == 0 or idx == len(rows):
                    print(f"  Обробка: {idx}/{len(rows)} (оброблено: {processed_count}, видалено міток: {removed_labels_count}, помилок: {error_count})", end='\r')
                
            except Exception as e:
                error_count += 1
                logger.error(f"Error processing card {card_id}: {e}")
        
        print("\n" + "=" * 80)
        print(f"  📊 РЕЗУЛЬТАТИ:")
        print(f"     Оброблено карток: {len(rows)}")
        print(f"     Карток з видаленими мітками: {processed_count}")
        print(f"     Видалено міток: {removed_labels_count}")
        print(f"     Помилок: {error_count}")
        print("=" * 80)
        print("\n  ✅ Видалення міток завершено!")
        
    except Exception as e:
        print(f"\n  ❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНатисніть Enter для продовження...")


async def sync_labels_on_all_cards():
    """Синхронізує мітки на всіх картках: видаляє старі та додає правильні"""
    print_header("СИНХРОНІЗАЦІЯ МІТОК НА ВСІХ КАРТКАХ TRELLO")
    
    if not TRELLO_API_KEY or not TRELLO_API_TOKEN or not TRELLO_BOARD_ID:
        print("  ❌ Не налаштовані Trello API credentials")
        print("     Потрібні: TRELLO_API_KEY, TRELLO_API_TOKEN, TRELLO_BOARD_ID")
        input("\nНатисніть Enter для продовження...")
        return
    
    try:
        db = VMDDatabase(DB_PATH)
        await db.initialize()
        
        # Отримуємо всі картки з БД - використовуємо нормалізовану колонку
        import aiosqlite
        async with aiosqlite.connect(db.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT tc.vehicle_id, tc.trello_card_id, v.vehicle_type
                FROM trello_cards tc
                JOIN vehicles v ON tc.vehicle_id = v.id
                WHERE tc.trello_card_id IS NOT NULL 
                  AND tc.trello_card_id != ''
            """)
            rows = await cursor.fetchall()
        
        if not rows:
            print("  ⚠️ Не знайдено карток для обробки")
            wait_for_enter()
            return
        
        print(f"\n  Знайдено {len(rows)} карток для синхронізації")
        print("     Будуть видалені старі мітки та додані правильні")
        
        confirm = input("\n  Синхронізувати мітки на всіх картках? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("  Операцію скасовано.")
            wait_for_enter()
            return
        
        trello = TrelloIntegration(
            api_key=TRELLO_API_KEY,
            api_token=TRELLO_API_TOKEN,
            board_id=TRELLO_BOARD_ID,
            list_id=TRELLO_LIST_ID,
            enabled=True,
        )
        
        updated_count = 0
        error_count = 0
        removed_labels_count = 0
        added_labels_count = 0
        
        print("\n  🔄 Синхронізація міток...")
        print("-" * 80)
        
        for idx, row in enumerate(rows, 1):
            card_id = row["trello_card_id"]
            vehicle_id = row["vehicle_id"]
            vehicle_type = row["vehicle_type"] or ""
            
            try:
                # Отримуємо очікувану мітку для цього типу авто
                expected_label_id = await get_trello_label_for_vehicle_type_async(vehicle_type, db) if vehicle_type else None
                
                # Отримуємо поточні мітки на картці
                current_labels = await trello.get_card_labels(card_id)
                current_label_ids = {label.get("id") for label in current_labels if label.get("id")}
                
                # Видаляємо ВСІ мітки окрім очікуваної
                removed_in_card = 0
                for label_id in current_label_ids:
                    if label_id != expected_label_id:
                        removed = await trello.remove_label_from_card(card_id, label_id)
                        if removed:
                            removed_in_card += 1
                            removed_labels_count += 1
                        await asyncio.sleep(0.2)  # Невелика затримка
                
                # Додаємо правильну мітку якщо її немає
                if expected_label_id and expected_label_id not in current_label_ids:
                    added = await trello.add_label_to_card(card_id, expected_label_id)
                    if added:
                        added_labels_count += 1
                    await asyncio.sleep(0.2)
                
                if removed_in_card > 0 or (expected_label_id and expected_label_id not in current_label_ids):
                    updated_count += 1
                
                if idx % 10 == 0 or idx == len(rows):
                    print(f"  Обробка: {idx}/{len(rows)} (оновлено: {updated_count}, видалено: {removed_labels_count}, додано: {added_labels_count}, помилок: {error_count})", end='\r')
                
            except Exception as e:
                error_count += 1
                logger.error(f"Error processing card {card_id}: {e}")
        
        print("\n" + "=" * 80)
        print(f"  📊 РЕЗУЛЬТАТИ:")
        print(f"     Оброблено карток: {len(rows)}")
        print(f"     Оновлено карток: {updated_count}")
        print(f"     Видалено міток: {removed_labels_count}")
        print(f"     Додано міток: {added_labels_count}")
        print(f"     Помилок: {error_count}")
        print("=" * 80)
        print("\n  ✅ Синхронізація міток завершено!")
        print("     Всі картки тепер мають правильні мітки.")
        
    except Exception as e:
        print(f"\n  ❌ Помилка: {e}")
        import traceback
        traceback.print_exc()
    
    input("\nНатисніть Enter для продовження...")


__all__ = [
    'show_trello_labels_menu',
    'create_trello_labels',
    'show_trello_labels_list',
    'check_vehicle_type_duplicates',
    'fix_vehicle_type_case',
    'fix_vehicle_type_typos_in_db',
    'update_label_colors_to_sky',
    'remove_all_labels_from_cards',
    'sync_labels_on_all_cards',
]
