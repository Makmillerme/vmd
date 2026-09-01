# MCP налаштування для VMD Extractor

## Проєкт

- **Python CLI:** корінь цього репозиторію (`vmd/`)
- **Шлях:** `d:\Project\mtruck\vmd`
- **База даних додатку:** **SQLite** — `vmd_extractor/data/db/vmd_data.sqlite3` (через `VMDDatabase`, `aiosqlite`)
- **Секрети:** лише в `.env` (IMAP, Trello, SMTP), не в репо

## Serena (user-serena)

**Призначення:** Редагування коду через символьний аналіз (LSP) — точні правки без переписування файлів.

**Проєкт:** `vmd`  
**Шлях:** `d:\Project\mtruck\vmd`

### Активація

При виклику /serena або перед редагуванням:

```
call_mcp_tool: server=user-serena, tool=activate_project, args={"project": "d:\\Project\\mtruck\\vmd"}
```

### Активні інструменти

| Інструмент | Призначення |
|------------|-------------|
| activate_project | Активація проєкту |
| find_symbol | Пошук символів (name_path_pattern, relative_path) |
| get_symbols_overview | Огляд символів у файлі |
| replace_symbol_body | Заміна тіла символу |
| insert_after_symbol | Вставка після символу |
| insert_before_symbol | Вставка перед символу |
| replace_content | Заміна патерну (literal/regex) |
| find_referencing_symbols | Пошук посилань на символ |
| search_for_pattern | Пошук патерну в проєкті |
| read_file | Читання файлу |
| create_text_file | Створення файлу |
| list_dir | Список файлів |
| find_file | Пошук файлу |
| write_memory | Запис у памʼять проєкту |
| read_memory | Читання памʼяті |
| edit_memory | Редагування памʼяті |
| rename_memory | Перейменування памʼяті |
| delete_memory | Видалення памʼяті |
| list_memories | Список памʼяток |
| rename_symbol | Перейменування символу з оновленням посилань |
| get_current_config | Поточна конфігурація |
| execute_shell_command | Виконання shell-кomанди |
| onboarding | Онбординг нового проєкту в Serena |

## PostgreSQL (user-postgres-ops)

**Призначення:** Операційне керування PostgreSQL stack на сервері (SSH + Docker).

**Важливо для VMD:**

| Контекст | Деталі |
|----------|--------|
| **Цей CLI** | Працює на **SQLite**; Postgres **не потрібен** для щоденної роботи |
| **БД на сервері** | `vmd_parser` (~9 MB) — окремий стек; можливе майбутнє використання або legacy |
| **Stack path** | `/root/apps/PostgressOps` |
| **Деплой додатку** | `/opt/vmd` (systemd timers, див. `deploy/README.md`) |

### Типові операції для VMD

- Health stack перед/після змін на сервері
- Backup `vmd_parser` перед міграціями (якщо колись перейдемо на Postgres)
- **Не** створювати/видаляти `vmd_parser` без явного підтвердження користувача

Деталі: [`rules/postgressops-server-operator.mdc`](rules/postgressops-server-operator.mdc), команда **`/PostgresOps`**.

## Інші MCP сервери

| Сервер | Релевантність для VMD |
|--------|----------------------|
| user-trello | Синхронізація карток, мітки, custom fields |
| user-filesystem | Файли в `D:\Project\`, `~/.cursor` |
| user-sequential-thinking | Планування (/plan) |
| user-shadcn | **Не застосовується** (немає Next.js UI) |
| user-next-devtools | **Не застосовується** |
| user-payloadcms-local | **Не застосовується** |

## Skills (VMD)

| Skill | Призначення |
|-------|-------------|
| vmd-workflow | Пайплайн розробки CLI |
| vmd-data | SQLite + postgres-ops контекст |
| strategic-planning | /plan |

## Команди Cursor

| Команда | Опис |
|---------|------|
| /plan | Sequential-thinking для планування |
| /docs | Документація (Python libs з `requirements.txt`) |
| /serena | Завдання через Serena MCP |
| /sync | Логувати зміни в Serena |
| /init | Ініціалізація / онбординг проєкту |
| /audit | Аудит Python CLI (async, I/O, БД, Trello) |
| /PostgresOps | PostgreSQL stack на сервері |
| /uk-layout | Декодування EN-розкладки → українська |
| /trello | Операції Trello |
