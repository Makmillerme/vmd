#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест запуску CLI
"""

import sys
import codecs
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("=" * 80)
print("  ТЕСТ ЗАПУСКУ CLI")
print("=" * 80)
print()

try:
    print("1. Тест імпорту config...")
    from vmd_extractor.config import (
        GOOGLE_DRIVE_ENABLED, GOOGLE_DRIVE_WEB_APP_URL, GOOGLE_DRIVE_API_KEY
    )
    print(f"   ✅ GOOGLE_DRIVE_ENABLED={GOOGLE_DRIVE_ENABLED}")
    print(f"   ✅ GOOGLE_DRIVE_WEB_APP_URL={'set' if GOOGLE_DRIVE_WEB_APP_URL else 'not set'}")
    print(f"   ✅ GOOGLE_DRIVE_API_KEY={'set' if GOOGLE_DRIVE_API_KEY else 'not set'}")
    print()
except Exception as e:
    print(f"   ❌ Помилка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("2. Тест імпорту GoogleDriveIntegration...")
    from vmd_extractor.brief.google_drive import GoogleDriveIntegration
    print("   ✅ GoogleDriveIntegration імпортовано")
    print()
except Exception as e:
    print(f"   ⚠️  Помилка (може бути нормально якщо не налаштовано): {e}")
    print()

try:
    print("3. Тест імпорту BriefDownloader...")
    from vmd_extractor.brief.downloader import BriefDownloader
    downloader = BriefDownloader()
    print("   ✅ BriefDownloader створено")
    print(f"   ✅ google_drive={'enabled' if downloader.google_drive else 'disabled'}")
    print()
except Exception as e:
    print(f"   ❌ Помилка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("4. Тест імпорту BriefOrchestrator...")
    from vmd_extractor.brief.orchestrator import BriefOrchestrator
    print("   ✅ BriefOrchestrator імпортовано")
    print()
except Exception as e:
    print(f"   ❌ Помилка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("5. Тест імпорту show_brief_menu...")
    from vmd_extractor.brief.cli import show_brief_menu
    print("   ✅ show_brief_menu імпортовано")
    print()
except Exception as e:
    print(f"   ❌ Помилка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

try:
    print("6. Тест імпорту main_menu_sync...")
    from vmd_extractor.cli.menus.main import main_menu_sync
    print("   ✅ main_menu_sync імпортовано")
    print()
except Exception as e:
    print(f"   ❌ Помилка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("=" * 80)
print("✅ Всі тести пройдено успішно!")
print("=" * 80)
