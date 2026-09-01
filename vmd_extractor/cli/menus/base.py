#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Базовий клас для всіх CLI меню.
Забезпечує:
- Централізовану ініціалізацію БД
- Контекстні менеджери
- Спільну логіку обробки помилок
- Уніфіковане управління ресурсами
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Callable, TypeVar, Coroutine
from contextlib import asynccontextmanager
from functools import wraps

from vmd_extractor.core.database import VMDDatabase
from vmd_extractor.config import DB_PATH

from .utils import (
    print_header, print_menu, get_user_choice, clear_screen, 
    wait_for_enter, get_date_input
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


class DatabaseContextManager:
    """Контекстний менеджер для роботи з БД"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self.db: Optional[VMDDatabase] = None
    
    async def __aenter__(self) -> VMDDatabase:
        """Ініціалізує та повертає БД"""
        self.db = VMDDatabase(self.db_path)
        await self.db.initialize()
        return self.db
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Очищення ресурсів (якщо потрібно)"""
        # VMDDatabase не потребує явного закриття
        self.db = None
        return False  # Не пригнічуємо виключення


def get_db_context(db_path: str = None) -> DatabaseContextManager:
    """
    Фабрична функція для створення контекстного менеджера БД.
    
    Використання:
        async with get_db_context() as db:
            # робота з db
            pass
    """
    return DatabaseContextManager(db_path)


def async_menu_handler(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, Optional[T]]]:
    """
    Декоратор для обробки помилок в async функціях меню.
    
    Використання:
        @async_menu_handler
        async def my_menu_function():
            # код
    """
    @wraps(func)
    async def wrapper(*args, **kwargs) -> Optional[T]:
        try:
            return await func(*args, **kwargs)
        except KeyboardInterrupt:
            print("\n\n  Операцію скасовано користувачем")
            return None
        except EOFError:
            print("\n  Переривання вводу")
            return None
        except Exception as e:
            logger.error("Помилка в %s: %s", func.__name__, e, exc_info=True)
            print(f"\n  ❌ Помилка: {e}")
            return None
    return wrapper


def sync_menu_handler(func: Callable[..., T]) -> Callable[..., Optional[T]]:
    """
    Декоратор для обробки помилок в sync функціях меню.
    
    Використання:
        @sync_menu_handler
        def my_sync_function():
            # код
    """
    @wraps(func)
    def wrapper(*args, **kwargs) -> Optional[T]:
        try:
            return func(*args, **kwargs)
        except KeyboardInterrupt:
            print("\n\n  Операцію скасовано користувачем")
            return None
        except EOFError:
            print("\n  Переривання вводу")
            return None
        except Exception as e:
            logger.error("Помилка в %s: %s", func.__name__, e, exc_info=True)
            print(f"\n  ❌ Помилка: {e}")
            return None
    return wrapper


class BaseMenu:
    """
    Базовий клас для всіх CLI меню.
    
    Забезпечує:
    - Централізовану ініціалізацію БД
    - Контекстні менеджери для ресурсів
    - Спільну логіку обробки помилок
    - Уніфіковану навігацію по меню
    
    Використання:
        class MyMenu(BaseMenu):
            async def run(self):
                async with self.db_context() as db:
                    # робота з db
                    pass
    """
    
    def __init__(self, db_path: str = None):
        """
        Ініціалізація меню.
        
        Args:
            db_path: Шлях до БД (за замовчуванням використовується DB_PATH з конфігу)
        """
        self._db_path = db_path or DB_PATH
        self._db: Optional[VMDDatabase] = None
        self._initialized = False
    
    @property
    def db_path(self) -> str:
        """Повертає шлях до БД"""
        return self._db_path
    
    @asynccontextmanager
    async def db_context(self):
        """
        Контекстний менеджер для роботи з БД.
        
        Використання:
            async with self.db_context() as db:
                # робота з db
                pass
        """
        async with get_db_context(self._db_path) as db:
            yield db
    
    async def get_db(self) -> VMDDatabase:
        """
        Отримує ініціалізований екземпляр БД.
        Кешує екземпляр для повторного використання.
        
        Returns:
            VMDDatabase: Ініціалізований екземпляр БД
        """
        if not self._initialized:
            self._db = VMDDatabase(self._db_path)
            await self._db.initialize()
            self._initialized = True
        return self._db
    
    async def run(self) -> None:
        """
        Головна функція меню.
        Має бути перевизначена в підкласах.
        """
        raise NotImplementedError("Subclass must implement run()")
    
    def show_header(self, title: str) -> None:
        """Показує заголовок меню"""
        print_header(title)
    
    def show_menu_options(self, options: Dict[str, str], title: str = "ВИБЕРІТЬ ОПЦІЮ") -> None:
        """Показує опції меню"""
        print_menu(options, title)
    
    def get_choice(self, options: Dict[str, str]) -> str:
        """Отримує вибір користувача"""
        return get_user_choice(options)
    
    def clear(self) -> None:
        """Очищає екран"""
        clear_screen()
    
    def wait(self, message: str = "\nНатисніть Enter для продовження...") -> None:
        """Очікує натискання Enter"""
        wait_for_enter(message)
    
    async def run_menu_loop(
        self, 
        options: Dict[str, str], 
        handlers: Dict[str, Callable], 
        title: str = "МЕНЮ"
    ) -> None:
        """
        Запускає цикл меню з обробниками.
        
        Args:
            options: Словник опцій меню {"1": "Опція 1", "0": "Вихід"}
            handlers: Словник обробників {"1": handler_func}
            title: Заголовок меню
        """
        while True:
            self.clear()
            self.show_menu_options(options, title)
            choice = self.get_choice(options)
            
            if choice == "0":
                break
            
            handler = handlers.get(choice)
            if handler:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler()
                    else:
                        handler()
                except KeyboardInterrupt:
                    print("\n  Операцію скасовано користувачем")
                except asyncio.CancelledError:
                    # Не плутати зі скасуванням користувачем: це cancel циклу подій (часто після blocking input() у async)
                    raise
                except Exception as e:
                    logger.error("Помилка в обробнику %s: %s", choice, e, exc_info=True)
                    print(f"\n  ❌ Помилка: {e}")
                
                self.wait()
            else:
                print(f"  Невідомий вибір: {choice}")
                self.wait()


class AsyncMenuRunner:
    """
    Утиліта для запуску async меню з синхронного коду.
    
    Використання:
        runner = AsyncMenuRunner()
        runner.run(my_async_menu_func())
    """
    
    @staticmethod
    def run(coro: Coroutine[Any, Any, T]) -> Optional[T]:
        """
        Запускає async корутину.
        
        Args:
            coro: Async корутина для виконання
            
        Returns:
            Результат виконання корутини або None при помилці
        """
        try:
            return asyncio.run(coro)
        except KeyboardInterrupt:
            print("\n\nОперацію скасовано користувачем")
            return None
        except Exception as e:
            logger.error("Критична помилка: %s", e, exc_info=True)
            print(f"\n\n❌ Критична помилка: {e}")
            return None


# Singleton instance for convenience
menu_runner = AsyncMenuRunner()




