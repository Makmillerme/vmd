#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Базовий клас для Trello меню.
"""

from ..base import BaseMenu
from vmd_extractor.config import TRELLO_ENABLED, TRELLO_API_KEY, TRELLO_API_TOKEN
from vmd_extractor.utils.trello_integration import TrelloIntegration


class BaseTrelloMenu(BaseMenu):
    """Базовий клас для Trello меню з перевіркою налаштувань"""
    
    def __init__(self, db_path=None):
        super().__init__(db_path)
        self._trello: TrelloIntegration = None
    
    def check_trello_enabled(self) -> bool:
        """Перевіряє чи увімкнена Trello інтеграція"""
        if not TRELLO_ENABLED:
            self.show_header("УПРАВЛІННЯ TRELLO")
            print("  Trello інтеграція вимкнена.")
            print("  Увімкніть її в .env файлі (TRELLO_ENABLED=true)")
            return False
        return True
    
    def check_trello_credentials(self) -> bool:
        """Перевіряє чи налаштовані Trello credentials"""
        if not TRELLO_API_KEY or not TRELLO_API_TOKEN:
            self.show_header("УПРАВЛІННЯ TRELLO")
            print("  Trello API credentials не налаштовані. Перевірте .env файл.")
            return False
        return True
    
    async def get_trello(self) -> TrelloIntegration:
        """Отримує TrelloIntegration"""
        if self._trello is None:
            self._trello = TrelloIntegration()
        return self._trello


