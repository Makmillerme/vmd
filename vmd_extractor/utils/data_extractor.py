#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Витягування даних з опису та XML елементів
ВАЖЛИВО: Не змінювати логіку - парсинг працює ідеально!
"""

import re
from typing import Dict
from .helpers import clean_num


def extract_vehicle_type_from_description(description: str) -> str:
    """
    Витягує тип транспорту з description з урахуванням можливих помилок.
    
    Повертає один з типів:
    - Автомобіль вантажний
    - Сідельний тягач
    - Контейнер (змінний кузов)
    - Напівпричіп
    - Моторний колісний транспортний засіб спеціального призначення
    - Причіп
    - Автомобіль легковий
    
    Перевірка виконується в порядку від більш специфічних до загальних типів.
    """
    if not description:
        return ""
    
    # Нормалізуємо текст: приводимо до нижнього регістру, замінюємо множинні пробіли
    text = description.strip().lower()
    text = re.sub(r'\s+', ' ', text)  # Замінюємо множинні пробіли на один
    # Видаляємо можливі номери на початку (1., 2., тощо)
    text = re.sub(r'^[0-9]+\.?\s*', '', text)
    
    # Визначаємо типи в порядку від більш специфічних до загальних
    # Примітка: "Моторний колісний транспортний засіб спеціального призначення" 
    # та інші невідомі типи будуть повертати "Інше" в кінці функції
    
    # 2. Сідельний тягач
    patterns_saddle = [
        r'сідельний\s+тягач',
        r'сідельний\s+тягач[аи]',
        r'сідельн[иі]й\s+тягач',
    ]
    for pattern in patterns_saddle:
        if re.search(pattern, text, re.IGNORECASE):
            return "Сідельний тягач"
    
    # 3. Напівпричіп
    patterns_semi = [
        r'напівпричіп',
        r'напів\s*причіп',
        r'напів-причіп',
        r'напів\s*прич[іи]п',
    ]
    for pattern in patterns_semi:
        if re.search(pattern, text, re.IGNORECASE):
            return "Напівпричіп"
    
    # 4. Контейнер (змінний кузов)
    patterns_container = [
        r'контейнер\s*\(?\s*змінний\s+кузов\s*\)?',
        r'контейнер\s*\(?\s*змінний\s+кузов',
        r'контейнер\s*\(?\s*змінний',
        r'контейнер\s+\(?\s*змінний\s+кузов',
    ]
    for pattern in patterns_container:
        if re.search(pattern, text, re.IGNORECASE):
            return "Контейнер (змінний кузов)"
    
    # 5. Автомобіль вантажний
    patterns_cargo = [
        r'автомобіль\s+вантажний',
        r'автомобіль\s+вантажн[иі]й',
        r'вантажний\s+автомобіль',
        r'вантажн[иі]й\s+автомобіль',
    ]
    for pattern in patterns_cargo:
        if re.search(pattern, text, re.IGNORECASE):
            # Для вантажного автомобіля додатково визначаємо тип кузова
            body_type = extract_body_type_for_cargo_vehicle(description)
            if body_type:
                # Замінюємо "Автомобіль вантажний" на конкретний тип кузова
                return body_type
            # Якщо тип кузова не знайдено - залишаємо "Автомобіль вантажний"
            return "Автомобіль вантажний"
    
    # 6. Автомобіль легковий
    patterns_passenger = [
        r'автомобіль\s+легковий',
        r'автомобіль\s+легков[иі]й',
        r'легковий\s+автомобіль',
        r'легков[иі]й\s+автомобіль',
    ]
    for pattern in patterns_passenger:
        if re.search(pattern, text, re.IGNORECASE):
            return "Автомобіль легковий"
    
    # 7. Причіп
    patterns_trailer = [
        r'причіп',
        r'прич[іи]п',
    ]
    for pattern in patterns_trailer:
        if re.search(pattern, text, re.IGNORECASE):
            return "Причіп"

    # 8. МКТЗ спеціального призначення для перевезення вантажів
    # У ВМД: «…спеціального призначення, призначений для перевезення вантажів» — вантажний авто.
    patterns_special_cargo = [
        r'моторний\s+колісний\s+транспортний\s+засіб\s+спеціального\s+призначення',
        r'мктз\s+спеціального\s+призначення',
    ]
    is_special_purpose = any(re.search(p, text, re.IGNORECASE) for p in patterns_special_cargo)
    is_cargo_purpose = bool(
        re.search(r'призначений\s+для\s+перевезення\s+вантаж', text, re.IGNORECASE)
        or re.search(r'перевезення\s+вантаж', text, re.IGNORECASE)
    )
    if is_special_purpose and is_cargo_purpose:
        body_type = extract_body_type_for_cargo_vehicle(description)
        if body_type:
            return body_type
        return "Автомобіль вантажний"

    # 9. Якщо нічого не знайдено - повертаємо "Інше"
    return "Інше"


def extract_body_type_for_cargo_vehicle(description: str) -> str:
    """
    Витягує тип кузова для вантажного автомобіля з опису.
    ПРІОРИТЕТ 1: Шукає явне вказання "тип кузова: [назва]"
    ПРІОРИТЕТ 2: Визначає за контекстом опису
    
    Виконує уніфікацію типів:
    - "Фургон рефрижератор" = "Фургон-рефрижератор" → "Фургон рефрижератор"
    - "Фургон бортовий тентований" = "Бортовий тентований" → "Фургон бортовий тентований"
    - "Фургон пластиковий" = "Фургон пастиковий" → "Фургон пластиковий"
    - "Бортовий" → "Фургон бортовий"
    
    Returns:
        Уніфікований тип кузова (наприклад, "фургон", "контейнеровоз") або порожній рядок
    """
    if not description:
        return ""
    
    text = description.strip()
    text_lower = text.lower()
    
    # ПРІОРИТЕТ 1: Шукаємо явне вказання "тип кузова: [назва]"
    body_type_match = re.search(
        r'тип\s+кузова[:\-]?\s*([^,\n\.]+)',
        text,
        re.IGNORECASE
    )
    if body_type_match:
        body_type = body_type_match.group(1).strip()
        # Видаляємо можливі зайві символи на початку
        body_type = re.sub(r'^[:\-]\s*', '', body_type)
        body_type = body_type.strip()
        
        if body_type and len(body_type) < 100:  # Не беремо занадто довгі
            # Уніфікація типів кузовів
            body_type_normalized = _normalize_body_type(body_type)
            if body_type_normalized:
                return body_type_normalized
    
    # ПРІОРИТЕТ 2: Визначаємо за контекстом опису
    # Контейнеровоз - найбільш специфічний
    if re.search(r'призначений\s+для\s+перевезення\s+контейнерів', text_lower, re.IGNORECASE):
        result = "контейнеровоз"
        # Виправляємо можливі помилки
        return fix_vehicle_type_typos(result)
    
    return ""


def fix_vehicle_type_typos(vehicle_type: str) -> str:
    """
    Виправляє типові помилки в типах транспортних засобів.
    
    Правила виправлення:
    - "контейнеровіз" → "контейнеровоз"
    - "контейнеровіз" (з великої) → "Контейнеровоз"
    - Інші типові помилки...
    
    Args:
        vehicle_type: Тип транспортного засобу (може містити помилки)
    
    Returns:
        Виправлений тип транспортного засобу
    """
    if not vehicle_type:
        return ""
    
    # Словник виправлень: помилка → правильний варіант
    typo_fixes = {
        "контейнеровіз": "контейнеровоз",
        "Контейнеровіз": "Контейнеровоз",
        "КОНТЕЙНЕРОВІЗ": "Контейнеровоз",
    }
    
    # Перевіряємо точні збіги
    if vehicle_type in typo_fixes:
        return typo_fixes[vehicle_type]
    
    # Перевіряємо з урахуванням регістру (case-insensitive)
    vehicle_type_lower = vehicle_type.lower()
    for typo, correct in typo_fixes.items():
        if vehicle_type_lower == typo.lower():
            # Зберігаємо оригінальний регістр першої літери
            if vehicle_type[0].isupper():
                return correct[0].upper() + correct[1:] if len(correct) > 1 else correct.upper()
            return correct.lower()
    
    # Виправлення через regex для складніших випадків
    # "контейнеровіз" → "контейнеровоз" (в будь-якому регістрі)
    fixed = re.sub(r'\bконтейнеровіз\b', 'контейнеровоз', vehicle_type, flags=re.IGNORECASE)
    
    # Якщо було виправлення, нормалізуємо регістр
    if fixed != vehicle_type:
        # Зберігаємо оригінальний регістр першої літери
        if vehicle_type[0].isupper():
            fixed = fixed[0].upper() + fixed[1:] if len(fixed) > 1 else fixed.upper()
    
    return fixed


def _normalize_body_type(body_type: str) -> str:
    """
    Уніфікує тип кузова, приводячи різні варіанти до єдиного стандарту.
    
    Правила уніфікації:
    - "Фургон рефрижератор" = "Фургон-рефрижератор" → "Фургон рефрижератор"
    - "Фургон бортовий тентований" = "Бортовий тентований" → "Фургон бортовий тентований"
    - "Фургон пластиковий" = "Фургон пастиковий" → "Фургон пластиковий"
    - "Бортовий" → "Фургон бортовий"
    - "Фургон" без додатків залишається "Фургон"
    """
    if not body_type:
        return ""
    
    # Спочатку виправляємо типові помилки
    body_type = fix_vehicle_type_typos(body_type)
    
    # Нормалізуємо: приводимо до нижнього регістру, видаляємо зайві пробіли
    normalized = body_type.strip().lower()
    normalized = re.sub(r'\s+', ' ', normalized)  # Множинні пробіли → один
    normalized = re.sub(r'[:\-]', ' ', normalized)  # Дефіси та двокрапки → пробіли
    normalized = re.sub(r'\s+', ' ', normalized)  # Знову нормалізуємо пробіли
    normalized = normalized.strip()
    
    # Уніфікація: виправлення опечаток
    # "пастиковий" → "пластиковий"
    normalized = re.sub(r'\bпастиковий\b', 'пластиковий', normalized, flags=re.IGNORECASE)
    
    # Уніфікація: "Фургон рефрижератор" = "Фургон-рефрижератор"
    if re.search(r'фургон\s*[-\s]?\s*рефрижератор', normalized, re.IGNORECASE):
        return "Фургон рефрижератор"
    
    # Уніфікація: "Фургон бортовий тентований" = "Бортовий тентований"
    if re.search(r'фургон\s+бортовий\s+тентований', normalized, re.IGNORECASE):
        return "Фургон бортовий тентований"
    if re.search(r'^бортовий\s+тентований$', normalized, re.IGNORECASE):
        return "Фургон бортовий тентований"
    
    # Уніфікація: "Фургон пластиковий" = "Фургон пастиковий" (вже виправлено вище)
    if re.search(r'фургон\s+пластиковий', normalized, re.IGNORECASE):
        return "Фургон пластиковий"
    
    # Уніфікація: "Бортовий" → "Фургон бортовий" (якщо не має додатків)
    if normalized == "бортовий":
        return "Фургон бортовий"
    
    # Уніфікація: "Бортовий самоскид" → "Фургон бортовий самоскид"
    if re.search(r'^бортовий\s+самоскид$', normalized, re.IGNORECASE):
        return "Фургон бортовий самоскид"
    
    # Уніфікація: "тентований" (тип кузова у ВМД) = "Тентована платформа"
    if normalized == "тентований" or re.search(r'^тентований\s+кузов?$', normalized, re.IGNORECASE):
        return "Тентована платформа"

    # Комбінований кузов (Transporter тощо) → Фургон
    if re.search(r'^комбінований\s+кузов$', normalized, re.IGNORECASE):
        return "Фургон"
    
    # Якщо просто "фургон" без додатків - залишаємо як є
    if normalized == "фургон":
        return "Фургон"
    
    # Якщо починається з "фургон" - нормалізуємо регістр
    if normalized.startswith("фургон"):
        # Відновлюємо правильний регістр: перша літера велика, решта як в оригіналі
        parts = body_type.strip().split()
        if parts:
            parts[0] = "Фургон"  # Завжди з великої літери
            return " ".join(parts)
        return "Фургон"
    
    # Якщо починається з "бортовий" - додаємо "Фургон"
    if normalized.startswith("бортовий"):
        parts = body_type.strip().split()
        if parts:
            parts[0] = "Фургон"  # Замінюємо "бортовий" на "Фургон"
            return " ".join(parts)
        return "Фургон бортовий"
    
    # Для інших типів (контейнеровоз, тощо) - нормалізуємо регістр
    # Перша літера велика, решта маленькі
    if body_type.strip():
        # Розбиваємо на слова та нормалізуємо кожне слово
        words = body_type.strip().split()
        normalized_words = []
        for word in words:
            if word:
                # Перша літера велика, решта маленькі
                normalized_word = word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper()
                normalized_words.append(normalized_word)
        result = " ".join(normalized_words)
        # Фінальна перевірка на помилки після нормалізації
        return fix_vehicle_type_typos(result)
    
    return fix_vehicle_type_typos(body_type.strip())


def extract_from_inv_det(inv_pos) -> Dict:
    """
    Витягує технічні дані з ccd_inv_det як fallback, якщо вони не знайдені в описі.
    Повертає словник з даними.
    """
    result = {}
    
    # Шукаємо всі ccd_inv_det елементи
    inv_det_list = inv_pos.findall("ccd_inv_det")
    
    for det in inv_det_list:
        code = det.findtext("ccd_id_code", "")
        value = det.findtext("ccd_id_value", "").strip()
        
        if not code or not value:
            continue
        
        # Мапінг кодів на поля
        # ccd_id_code="93" - вантажопідйомність (в тонах, потрібно перевести в кг)
        if code == "93" and value and value != "-" and value != "0":
            try:
                payload_tons = float(value.replace(",", "."))
                result["payload_kg"] = int(payload_tons * 1000)  # Переводимо в кг
            except (ValueError, TypeError):
                pass
        
        # ccd_id_code="94" - маса в разі повного навантаження (в тонах, потрібно перевести в кг)
        elif code == "94" and value and value != "-" and value != "0":
            try:
                gross_weight_tons = float(value.replace(",", "."))
                result["gross_weight_kg"] = int(gross_weight_tons * 1000)  # Переводимо в кг
            except (ValueError, TypeError):
                pass
        
        # ccd_id_code="87" - об'єм двигуна (в см3)
        elif code == "87" and value and value != "-" and value != "0":
            try:
                result["engine_cm3"] = int(float(value))
            except (ValueError, TypeError):
                pass
        
        # ccd_id_code="85" - кількість місць
        elif code == "85" and value and value != "-" and value != "0":
            try:
                result["seats"] = int(float(value))
            except (ValueError, TypeError):
                pass
        
        # ccd_id_code="134" - колісна формула
        elif code == "134" and value and value != "-":
            wheel_formula = value.replace("*", "x").replace("Х", "x").replace("х", "x").upper()
            result["wheel_formula"] = wheel_formula
        
        # ccd_id_code="90" або "122" - рік виготовлення
        elif code in ["90", "122"] and value and value != "-" and value != "0":
            try:
                year = int(value)
                if 1900 <= year <= 2100:  # Валідація року
                    if "year_model" not in result:
                        result["year_model"] = year
                    if "year_calendar" not in result:
                        result["year_calendar"] = year
            except (ValueError, TypeError):
                pass

        # ccd_id_code="96" - марка
        elif code == "96" and value:
            result["brand"] = value

        # ccd_id_code="97" - модель
        elif code == "97" and value:
            result["model"] = value

        # ccd_id_code="98" - VIN/номер рами
        elif code == "98" and value:
            result["vin"] = value.upper()
    
    return result


def parse_tech_from_description(desc: str):
    """
    Парсинг технічних даних з опису (ccd_31_01).
    ВАЖЛИВО: Не змінювати логіку - працює ідеально!
    """
    if not desc:
        return {}
    text = desc.replace("\n", " ").replace("\r", " ")

    patterns = {
        "brand": r"марка[:\-]?\s*\"?([\w\-\.\s]+?)\"?(?:,|\s)",
        "model": r"модель[:\-]?\s*\"?([\w\-\.\s]+?)\"?(?:,|\s)",
        "vin": r"(?:VIN|№\s*(?:кузова|шасі|рами|кузова/шасі|рами/кузова|кузова/рами))[:\-\s]*([A-HJ-NPR-Z0-9]{11,20})",
        # S/N (серійний номер) для контейнерів - враховує різні формати
        "serial_number": r"(?:S/N|S\.N\.|серійний\s+номер)[:\-\s]+([A-Z0-9\-]+)",
        "engine_cm3": r"об[''`]?єм\s*двигуна[:\-]?\s*([\d\s]+)\s*см3",
        # Покращений regex для power_kw - враховує "потужність двигуна" та "потужність"
        "power_kw": r"потужн(?:ість|iсть)(?:\s+двигуна)?\s*[:\-]?\s*([\d\s]+)\s*кВт",
        "seats": r"(?:кількість\s*місць[^:]*|місць)[ :\-]*([0-9]+)",
        "wheel_formula": r"колісна\s*формула[:\-]?\s*([0-9xXхХ]{3,5})",
        "payload_kg": r"вантажопідйомність[:\-]?\s*([\d\s]+)\s*кг",
        # Покращений regex для gross_weight_kg - більш гнучкий
        "gross_weight_kg": r"маса\s*в\s*разі\s*повного\s*навантаження[:\-]?\s*([\d\s]+)\s*кг",
        "year_model": r"модельний\s*рік[^:]*[:\-]?\s*(\d{4})",
        "year_calendar": r"календарний\s*рік[^:]*[:\-]?\s*(\d{4})"
    }

    res = {}
    for k, pat in patterns.items():
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            res[k] = m.group(1).strip()

    # Визначення wheel_formula з тексту, якщо не знайдено явно
    if not res.get("wheel_formula"):
        # Шукаємо описи кількості осей/вісей (різні варіанти написання)
        if re.search(r"три\s+осі|3\s+осі|три\s+ос[іи]", text, re.IGNORECASE):
            res["wheel_formula"] = "3x2"  # Три осі, дві ведучі
        elif re.search(r"дві\s+осі|2\s+осі|дві\s+ос[іи]", text, re.IGNORECASE):
            res["wheel_formula"] = "2x2"  # Дві осі, дві ведучі
        elif re.search(r"одновісьний|одна\s+вісь|1\s+вісь|однов[іи]сьний", text, re.IGNORECASE):
            res["wheel_formula"] = "1x1"  # Одна вісь
        elif re.search(r"чотири\s+осі|4\s+осі|чотири\s+ос[іи]", text, re.IGNORECASE):
            res["wheel_formula"] = "4x2"  # Чотири осі, дві ведучі

    if res.get("wheel_formula"):
        res["wheel_formula"] = res["wheel_formula"].replace("Х", "x").replace("х", "x").upper()

    for n in ["engine_cm3", "power_kw", "seats", "payload_kg", "gross_weight_kg", "year_model", "year_calendar"]:
        if n in res:
            res[n] = clean_num(res[n])

    return res



