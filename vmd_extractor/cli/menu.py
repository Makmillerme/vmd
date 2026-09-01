#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Інтерактивне меню управління VMD Extractor
Перенаправляє на нову модульну структуру меню.
"""

import sys
import os
import logging

# Додаємо поточну директорію до шляху
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from vmd_extractor.cli.menus.main import main_menu
except ImportError:
    # Fallback for direct execution if path is not set correctly
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from vmd_extractor.cli.menus.main import main_menu

# Налаштування логування (зменшуємо технічні деталі)
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Приховуємо детальні логи від модулів
logging.getLogger("vmd_extractor.core.downloader").setLevel(logging.WARNING)
logging.getLogger("vmd_extractor.core.processor").setLevel(logging.WARNING)
logging.getLogger("vmd_extractor.core.parser").setLevel(logging.WARNING)
logging.getLogger("vmd_extractor.utils").setLevel(logging.WARNING)

# Suppress other noisy loggers
logging.getLogger("aiosqlite").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

if __name__ == "__main__":
    try:
        from vmd_extractor.cli.menus.main import main_menu_sync
        main_menu_sync()
    except KeyboardInterrupt:
        print("\n\nДо побачення!\n")
        sys.exit(0)
