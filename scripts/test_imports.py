#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест всіх імпортів проекту
"""

import sys
import codecs
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_import(name, module_path):
    """Тестує імпорт модуля"""
    try:
        __import__(module_path)
        print(f"✅ {name}")
        return True
    except Exception as e:
        print(f"❌ {name}: {e}")
        return False

print("=" * 80)
print("  ТЕСТ ІМПОРТІВ ПРОЕКТУ")
print("=" * 80)
print()

errors = []

# Core modules
print("Core модулі:")
errors.append(not test_import("vmd_extractor.core.database", "vmd_extractor.core.database"))
errors.append(not test_import("vmd_extractor.core.exporter", "vmd_extractor.core.exporter"))
errors.append(not test_import("vmd_extractor.core.orchestrator", "vmd_extractor.core.orchestrator"))
print()

# Brief modules
print("Brief модулі:")
errors.append(not test_import("vmd_extractor.brief.processor", "vmd_extractor.brief.processor"))
errors.append(not test_import("vmd_extractor.brief.parser", "vmd_extractor.brief.parser"))
errors.append(not test_import("vmd_extractor.brief.database", "vmd_extractor.brief.database"))
errors.append(not test_import("vmd_extractor.brief.pdf_converter", "vmd_extractor.brief.pdf_converter"))
errors.append(not test_import("vmd_extractor.brief.downloader", "vmd_extractor.brief.downloader"))
errors.append(not test_import("vmd_extractor.brief.google_drive", "vmd_extractor.brief.google_drive"))
errors.append(not test_import("vmd_extractor.brief.orchestrator", "vmd_extractor.brief.orchestrator"))
errors.append(not test_import("vmd_extractor.brief.cli", "vmd_extractor.brief.cli"))
print()

# CLI modules
print("CLI модулі:")
errors.append(not test_import("vmd_extractor.cli.menus.main", "vmd_extractor.cli.menus.main"))
errors.append(not test_import("vmd_extractor.cli.menus.database", "vmd_extractor.cli.menus.database"))
errors.append(not test_import("vmd_extractor.cli.menus.download", "vmd_extractor.cli.menus.download"))
errors.append(not test_import("vmd_extractor.cli.menus.trello.menu", "vmd_extractor.cli.menus.trello.menu"))
print()

# Utils
print("Utils модулі:")
errors.append(not test_import("vmd_extractor.utils.trello_integration", "vmd_extractor.utils.trello_integration"))
errors.append(not test_import("vmd_extractor.utils.xml_parser", "vmd_extractor.utils.xml_parser"))
print()

# Config
print("Config:")
errors.append(not test_import("vmd_extractor.config", "vmd_extractor.config"))
print()

print("=" * 80)
if any(errors):
    print(f"❌ Знайдено {sum(errors)} помилок імпорту")
    sys.exit(1)
else:
    print("✅ Всі імпорти працюють правильно!")
    sys.exit(0)
