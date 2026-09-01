#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсинг XML документів ВМД
ВАЖЛИВО: Не змінювати логіку - парсинг працює ідеально!
"""

import xml.etree.ElementTree as ET
from typing import List, Dict
from .data_extractor import (
    extract_vehicle_type_from_description,
    extract_from_inv_det,
    parse_tech_from_description
)


def parse_date_from_xml(root):
    """
    Парсинг дати створення ВМД з XML документа.
    
    Args:
        root: Корінь XML дерева
    
    Returns:
        Дата у форматі YYYY-MM-DD або порожній рядок
    """
    # Спочатку пробуємо ccd_registered (дата реєстрації ВМД)
    registered = root.findtext("ccd_registered", "")
    if registered:
        try:
            # Формат: 20250611T185020 -> 2025-06-11
            date_part = registered.split('T')[0]
            if len(date_part) == 8:
                year = date_part[:4]
                month = date_part[4:6]
                day = date_part[6:8]
                return f"{year}-{month}-{day}"
        except:
            pass
    
    # Якщо не знайшли, пробуємо ccd_submitted (дата подачі)
    submitted = root.findtext("ccd_submitted", "")
    if submitted:
        try:
            date_part = submitted.split('T')[0]
            if len(date_part) == 8:
                year = date_part[:4]
                month = date_part[4:6]
                day = date_part[6:8]
                return f"{year}-{month}-{day}"
        except:
            pass
    
    return ""


def parse_doc2(xml_path: str, source_name: str) -> List[Dict]:
    """
    Парсинг doc2.xml файлу ВМД.
    ВАЖЛИВО: Не змінювати логіку - працює ідеально!
    
    Args:
        xml_path: Шлях до doc2.xml файлу
        source_name: Назва джерельного файлу
    
    Returns:
        Список словників з даними про транспортні засоби
    """
    rows = []
    try:
        # Читаємо XML файл, спочатку пробуємо UTF-8, потім windows-1251
        xml_content = None
        encodings = ['utf-8', 'windows-1251', 'cp1251']
        
        for encoding in encodings:
            try:
                with open(xml_path, 'r', encoding=encoding) as f:
                    xml_content = f.read()
                break
            except (UnicodeDecodeError, LookupError):
                continue
        
        if xml_content is None:
            raise ValueError(f"Не вдалося прочитати файл {xml_path} з жодного кодування")
        
        root = ET.fromstring(xml_content)

        mrn = root.findtext("MRN") or root.findtext("ccd_mrn") or ""
        rate = root.findtext("ccd_23_01") or root.findtext("ccd_dcc_cur_rate") or ""
        
        # Отримуємо дату створення ВМД з XML
        vmd_creation_date = parse_date_from_xml(root)

        for g in root.iter("ccd_goods"):
            base = {
                "source_file": source_name,
                "mrn": mrn,
                "create_at_ccd": vmd_creation_date,
                "uktzed": g.findtext("ccd_33_01", ""),
                "description": (g.findtext("ccd_31_01", "") or "").strip(),
                
                # ВАЖЛИВО: Використовуємо тільки інвойсну вагу
                "gross_weight": "",  # Буде заповнено з інвойсу
                "net_weight": "",    # Буде заповнено з інвойсу
                "quantity": g.findtext("ccd_31_04", ""),     # Виправлено: було ccd_inv_qty
                
                # Фінансові поля (тільки в UAH)
                "customs_value": g.findtext("ccd_45_01", "") or g.findtext("ccd_dcc_sum", ""),
            }

            # Читаємо дані з ccd_inv_pos (якщо є)
            inv_pos = g.find("ccd_inv_pos")
            if inv_pos is not None:
                base["producer_country"] = inv_pos.findtext("ccd_inv_prod_cnt", "")
                # ВАЖЛИВО: Використовуємо тільки інвойсну вагу
                base["gross_weight"] = inv_pos.findtext("ccd_inv_wb", "")  # Інвойсна вага брутто
                base["net_weight"] = inv_pos.findtext("ccd_inv_wn", "")    # Інвойсна вага нетто
            else:
                base["producer_country"] = ""
            
            # Витягуємо тип техніки з description (не з invoice_name)
            vehicle_type = extract_vehicle_type_from_description(base["description"])
            # Виправляємо можливі помилки в типі
            from ..utils.data_extractor import fix_vehicle_type_typos
            base["vehicle_type"] = fix_vehicle_type_typos(vehicle_type)

            # Читаємо дані з ccd_goods_dcc (якщо є)
            dcc = g.find("ccd_goods_dcc")
            if dcc is not None:
                pass  # Видалено dcc_rate та dcc_value

            # Податки (ccd_47_*) - не парсимо, не потрібні

            # ПРІОРИТЕТ: Спочатку витягуємо дані з ccd_inv_det (структуровані дані)
            inv_det_data = {}
            if inv_pos is not None:
                inv_det_data = extract_from_inv_det(inv_pos)
                # Оновлюємо базові поля з пріоритетом ccd_inv_det
                for key, value in inv_det_data.items():
                    if value:  # Тільки якщо значення не порожнє
                        base[key] = value
            
            # Fallback: парсинг з опису (тільки для полів, які не знайдені в ccd_inv_det)
            tech = parse_tech_from_description(base["description"])
            for key, value in tech.items():
                # Оновлюємо тільки якщо поле не було знайдено в ccd_inv_det
                if key not in base or not base[key]:
                    base[key] = value
            
            # Для контейнерів та спецтехніки: serial_number використовується як VIN тільки якщо VIN відсутній
            # Перевага завжди надається VIN, serial_number - тільки як fallback
            vehicle_type = base.get("vehicle_type", "")
            vehicle_type_lower = vehicle_type.lower()
            is_container = "контейнер" in vehicle_type_lower or "змінний кузов" in vehicle_type_lower
            is_special_equipment = "спеціальн" in vehicle_type_lower or "спецтехніка" in vehicle_type_lower
            
            if is_container or is_special_equipment:
                # Для контейнерів та спецтехніки: якщо немає VIN, але є serial_number - використовуємо його як VIN
                if not base.get("vin") and tech.get("serial_number"):
                    base["vin"] = tech.get("serial_number")
                # Якщо є VIN - використовуємо його (не замінюємо на serial_number)
            
            rows.append(base)

    except Exception as e:
        rows.append({"source_file": source_name, "error": f"Помилка читання {xml_path}: {e}"})
    return rows



