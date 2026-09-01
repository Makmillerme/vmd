# VMD Extractor

Асинхронна система завантаження, обробки та експорту Вантажних Митних Декларацій (ВМД).

## 🚀 Функціонал

- **Асинхронне завантаження** ВМД з пошти UKR.NET (без обмеження кількості)
- **Фільтрація по датах** - завантаження за конкретний діапазон дат
- **Звіт про ВМД** - перевірка наявності ВМД на пошті без завантаження
- **Паралельна обробка** файлів (розпакування, парсинг)
- **Автоматичний парсинг** даних з XML документів
- **Збереження PDF** - автоматичне збереження та перейменування PDF файлів
- **Експорт в Excel** з нормалізованими даними

## 📁 Структура проекту

```
vmd/
├── run.py                    # 🚀 Головний скрипт запуску (використовуйте цей!)
├── vmd_extractor/           # Основна папка з модулями
│   ├── core/                # Основна логіка
│   │   ├── orchestrator.py  # Головний оркестратор
│   │   ├── downloader.py    # Завантаження з пошти
│   │   ├── processor.py     # Обробка файлів
│   │   ├── parser.py        # Парсинг XML
│   │   └── exporter.py      # Експорт в Excel
│   ├── utils/               # Утиліти
│   │   ├── helpers.py        # Загальні утиліти
│   │   ├── imap_utils.py    # IMAP функції
│   │   ├── xml_parser.py    # Парсинг XML
│   │   ├── data_extractor.py # Витяг даних
│   │   └── pdf_handler.py   # Обробка PDF
│   ├── cli/                 # CLI інтерфейси
│   │   ├── extractor.py     # Головний CLI
│   │   ├── report.py        # Звіт про ВМД
│   │   └── process_extracted.py # Обробка розпакованих
│   ├── data/                # Дані та результати
│   │   ├── files/           # Завантажені .imfx файли
│   │   ├── extract_data/    # Експортовані Excel файли
│   │   ├── pdf/             # PDF файли ВМД
│   │   └── temp_extracted/  # Тимчасові розпаковані
│   └── config.py            # Централізована конфігурація
├── requirements.txt         # Залежності Python
├── .env                     # Налаштування (створити самостійно)
└── venv/                    # Віртуальне середовище (створюється автоматично)
```

**Примітка про `venv/`:**
- Це стандартне віртуальне середовище Python з встановленими пакетами
- Займає багато місця (~200-300MB)
- Можна видалити - воно створиться автоматично при запуску `run.py`
- Додано в `.gitignore` (не потрапляє в git)

## 🗺️ Технічний майндмеп

### Загальна схема

```
┌─────────────────────────────────────────────────────────────────┐
│                    VMD EXTRACTOR - ПАЙПЛАЙН                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌─────────────────────────────────────┐
        │  1. ЗВІТ ПРО ВМД (опціонально)      │
        └─────────────────────────────────────┘
                              │
        ┌─────────────────────────────────────┐
        │  2. ЗАВАНТАЖУВАЧ (DOWNLOADER)       │
        └─────────────────────────────────────┘
                              │
        ┌─────────────────────────────────────┐
        │  3. ОБРОБНИК (PROCESSOR)            │
        └─────────────────────────────────────┘
                              │
        ┌─────────────────────────────────────┐
        │  4. ПАРСЕР (PARSER)                 │
        └─────────────────────────────────────┘
                              │
        ┌─────────────────────────────────────┐
        │  5. ЗБЕРЕЖЕННЯ ДАНИХ                │
        └─────────────────────────────────────┘
                              │
        ┌─────────────────────────────────────┐
        │  6. ОЧИЩЕННЯ                        │
        └─────────────────────────────────────┘
```

### Детальний опис етапів

1. **Етап 1 — Звіт про ВМД**
   - `cli/report.py`: підключення до IMAP, сканування INBOX/Read, підрахунок ВМД, побудова звіту, повернення UID.

2. **Етап 2 — Downloader**
   - `connect_imap()`, `build_imap_search_criteria()`, `check_vmd_attachment_lightweight()`.
   - Перевірка відправника, розміру (MIN/MAX_SIZE_KB), SHA256 і хешів з БД (preload).
   - Завантаження з унікальною назвою `timestamp__sha__original.imfx`, затримка `DOWNLOAD_DELAY`.

3. **Етап 3 — Processor**
   - `extract_imfx()` розпаковує `.imfx` → `temp_extracted/*_unzipped`.
   - Валідована наявність `doc2.xml`, пошук PDF (`doc3.pdf` та ін.).
   - Готує `processed_files` з метаданими (sha, size, path, pdf_path).

4. **Етап 4 — Parser**
   - `parse_doc2()` читає XML у UTF-8 / win-1251.
   - `AsyncVMDParser` збирає технічні, фінансові, датовані поля, визначає тип техніки.

5. **Етап 5 — Збереження даних**
   - `attach_pdf_links()` перейменовує PDF (марка + модель + VIN), перевіряє існуючі файли, не перезаписує.
   - `VMDDatabase.persist_pipeline_run()` робить транзакцію:
     - `email_messages`: метадані листів, `updated_at`.
     - `processed_files`: filename, sha256, stored_path, window_start/end.
     - `vehicles`: payload_json, `pdf_url`, зв’язок з processed_file.
     - `sync_runs`: контрольні точки кожного запуску (навіть без нових файлів).
   - `ExcelExporter.export_all_tables()` читає напряму з SQLite, створює багатолистовий файл (vehicles, processed_files, email_messages, sync_runs), форматує дати/час.

6. **Етап 6 — Очищення**
   - `_cleanup_downloaded_files()` видаляє `data/files/*.imfx`.
   - `_cleanup_temp_extracted()` прибирає `temp_extracted/*_unzipped`.

### Потік даних

```
EMAIL → Downloader → Processor → Parser → Database → Excel/PDF → Cleanup
          │             │          │           │           │         │
          ▼             ▼          ▼           ▼           ▼         ▼
     files/*.imfx   temp_extracted   parsed dicts   SQLite (4 таблиці) PDF/Excel
```

### Ключові таблиці БД

- `email_messages`: folder, UID, sender, subject, sent_at, created_at, updated_at.
- `processed_files`: sha256 (UNIQUE), filename, stored_path, downloaded_at, window_start/end, size_kb.
- `vehicles`: processed_file_id, MRN, VIN, model, customs_value, payload_json, pdf_url.
- `sync_runs`: window_start/end, status, files_downloaded, timestamps.

#### Видалені колонки (не зберігаємо та не експортуємо)
- `invoice_name` (XML `ccd_inv_name`)
- `vat_percent` / `vat_amount_uah` (XML `ccd_47_tax`, `ccd_47_sum`)
- `trademark` (XML `ccd_inv_tm`)
- `producer` (XML `ccd_inv_prod_name`)
- `origin_country` (XML `ccd_34_01`)

Ці поля допоміжні, тому були виключені з парсингу, БД та Excel.

Поля прибрані з парсингу, БД та Excel (історичні дані автоматично очищуємо міграціями/експортом).

### Автономний режим

- `run_auto.py` читає останній успішний `sync_run`, визначає новий діапазон, запускає `cli/extractor`.
- `systemd` сервіс + таймер (08:00 та 17:00) — інструкції нижче.

## ⚙️ Встановлення

### Автоматичне встановлення (рекомендовано):

Просто запустіть головний скрипт - він автоматично створить все необхідне:

```bash
python run.py
```

Скрипт автоматично:
- Створить віртуальне середовище (якщо немає)
- Встановить всі залежності
- Запустить процес завантаження та парсингу

### Ручне встановлення:

1. **Створіть віртуальне середовище:**
```bash
python -m venv venv
```

2. **Активуйте віртуальне середовище:**
```bash
# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

3. **Встановіть залежності:**
```bash
pip install -r requirements.txt
```

4. **Створіть файл `.env` в корені проекту:**
```env
# IMAP налаштування
IMAP_HOST=imap.ukr.net
IMAP_PORT=993
IMAP_USER=your_mail@ukr.net
IMAP_PASS=your_imap_app_password

# Фільтри файлів (розмір в KB)
MIN_SIZE_KB=280
MAX_SIZE_KB=320

# Затримка між завантаженнями (секунди) - опціонально, за замовчуванням 2.0
DOWNLOAD_DELAY=2.0

# Часовий пояс системи (за замовчуванням Europe/Kyiv)
LOCAL_TIMEZONE=Europe/Kyiv
```

**Примітка:** 
- `DOWNLOAD_DELAY` - опціональний параметр. Якщо не вказано, використовується значення 2.0 секунди.
- Можна скопіювати `.env.example` та заповнити своїми даними.

## 🎯 Використання

### Запуск через головний скрипт (рекомендовано):

```bash
# Завантаження за поточний день
python run.py --today

# Завантаження за останні 7 днів
python run.py --days 7

# Завантаження за конкретний діапазон
python run.py --from 2025-01-01 --to 2025-01-31

# Завантаження з конкретної дати до сьогодні
python run.py --from 2025-01-01

# Завантаження до конкретної дати
python run.py --to 2025-01-31

# Завантаження всіх доступних ВМД (без фільтрації)
python run.py

# Вимкнення сортування
python run.py --no-sort
```

### Прямий запуск (якщо venv вже налаштовано):

```bash
# Активуйте venv
venv\Scripts\activate  # Windows
# або
source venv/bin/activate  # Linux/Mac

# Запустіть extractor з параметрами
python -m vmd_extractor.cli.extractor --today
python -m vmd_extractor.cli.extractor --from 2025-01-01 --to 2025-01-31
python -m vmd_extractor.cli.extractor --days 7

# Звіт про ВМД (без завантаження)
python -m vmd_extractor.cli.report --days 7
python -m vmd_extractor.cli.report --from 2025-01-01 --to 2025-01-31
python -m vmd_extractor.cli.report --today

# Обробка розпакованих файлів (якщо файли вже розпаковані)
python -m vmd_extractor.cli.process_extracted
```

## 🖥️ Розгортання на сервері (Ubuntu)

### Ручний запуск (одноразовий прогін)
```bash
python run.py --from 2025-11-01 --to 2025-11-17
```

### Автономний режим (`run_auto.py`)

**Розклад:** перевірка ВМД о **08:00, 12:00, 16:00, 20:00**; email-розсилка за минулий тиждень — **щопонеділка о 09:00**.

1. Переконайтесь, що `.env` заповнений бойовими доступами (IMAP, Trello, SMTP, `EMAIL=...`).
2. Одноразовий запуск:
   ```bash
   python run_auto.py --once
   python run_auto.py --weekly-report   # тижневий звіт
   ```
3. Фоновий daemon (без systemd):
   ```bash
   python run_auto.py
   ```
4. **Рекомендовано на сервері:** systemd timers — див. [`deploy/README.md`](deploy/README.md).

## 🏷️ Мітки Trello

Щоб оформити картки та списки у Trello, нам потрібно знати доступні мітки (labels).  
У картку `691dc89ce2565e32d845170b` вже додані всі мітки — скористайтеся скриптом нижче, щоб підтягнути їхні параметри та копіювати в таблицю.

### Як отримати мітки

```bash
python scripts/list_trello_labels.py --card-id 691dc89ce2565e32d845170b
```

- Скрипт використовує налаштування з `.env`: `TRELLO_API_KEY`, `TRELLO_API_TOKEN`, `TRELLO_BOARD_ID`, `TRELLO_LIST_ID`.
- За потреби можна зберегти ID картки у `.env` як `TRELLO_LABEL_CARD_ID`, тоді аргумент `--card-id` буде не потрібен.
- Після запуску ви отримаєте таблицю з назвою, кольором та ID кожної мітки — скопіюйте її у таблицю нижче.

### Поточний список міток

| Назва                      | Колір  | ID |
|----------------------------|--------|--------------------------------|
| Контейнер (змінний кузов)  | green  | 68d52ea73ee85a752e868b2a       |
| Автомобіль вантажний       | yellow | 68d52ea73ee85a752e868b29       |
| Сідельний тягач            | red    | 68d52ea73ee85a752e868b2b       |
| Причіп                     | purple | 68d52ea73ee85a752e868b2c       |
| Напівпричіп                | blue   | 68d52ea73ee85a752e868b2d       |
| Інше                       | pink   | 691d86f856167c6336a5e992       |

> Картки отримують мітку автоматично залежно від `vehicle_type` у БД. Значення можна перевизначити в `.env` (див. змінні `TRELLO_LABEL_*_ID`).

Доступні змінні середовища для перевизначення:

```env
TRELLO_LABEL_CONTAINER_ID=68d52ea73ee85a752e868b2a
TRELLO_LABEL_TRUCK_ID=68d52ea73ee85a752e868b29
TRELLO_LABEL_SEMITRACTOR_ID=68d52ea73ee85a752e868b2b
TRELLO_LABEL_TRAILER_ID=68d52ea73ee85a752e868b2c
TRELLO_LABEL_SEMITRAILER_ID=68d52ea73ee85a752e868b2d
TRELLO_LABEL_OTHER_ID=691d86f856167c6336a5e992
```

### Ручне додавання карток за VIN

Через меню `run.py` можна вручну додати (або відновити) картки в Trello за списком VIN:

1. Запустіть `python run.py` без аргументів і оберіть розділ **3. Управління Trello**.
2. Виберіть опцію **5. Додати картки за VIN**.
3. Введіть VIN-коди у форматі `VIN1, VIN2, VIN3` (через кому, регістр неважливий).
4. Система:
   - перевірить наявність відповідних ВМД у БД;
   - виключить легкові авто та VIN, які вже мають актуальну картку;
   - запустить існуючий пайплайн створення карток (з мітками, PDF, оновленням `trello_cards`).

Цей режим зручний, коли потрібно швидко відновити або вручну додати кілька машин без повторного завантаження пошти.

### Запуск як systemd сервіс + таймер

Повна інструкція: [`deploy/README.md`](deploy/README.md). Коротко:

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
# Відредагуйте WorkingDirectory=/opt/vmd у .service файлах за потреби
sudo systemctl daemon-reload
sudo systemctl enable --now vmd-extractor.timer vmd-mailing.timer
```

Таймери:
- **vmd-extractor.timer** — 08:00, 12:00, 16:00, 20:00
- **vmd-mailing.timer** — понеділок 09:00

Логи: `journalctl -u vmd-extractor.service`, `journalctl -u vmd-mailing.service`.

### Health-check / smoke-test
```bash
# Перевірити, що останній синхронний запуск був успішним і не старіший за 12 годин
python run_auto.py --health-check

# Задати власний поріг (наприклад, 6 годин)
python run_auto.py --health-check --max-age-hours 6
```
Можна використовувати в `systemd` `ExecStartPre`/`ExecStartPost` або в моніторингу.

### Програмний запуск:

```python
import asyncio
from datetime import date
from vmd_extractor.core import VMDOrchestrator

async def main():
    # Завантаження за діапазон дат (завантажує ВСІ ВМД в діапазоні)
    orchestrator = VMDOrchestrator(
        date_from=date(2025, 1, 1),
        date_to=date(2025, 1, 31),
        sort_by_date=True
    )
    results = await orchestrator.run_full_pipeline()
    print(f"Завантажено: {results['downloaded']} файлів")
    print(f"Оброблено: {results['processed']} файлів")
    print(f"Спарсено: {results['parsed_records']} записів")
    print(f"Excel: {results['excel_path']}")

asyncio.run(main())
```

## 📊 Процес обробки

1. **Звіт** - Перевірка наявності ВМД за вказаний діапазон дат (опціонально, автоматично)
2. **Завантаження** - Асинхронне завантаження ВСІХ ВМД файлів з пошти (без обмеження кількості)
3. **Розпакування** - Паралельне розпакування .imfx архівів
4. **Парсинг** - Витяг даних з doc2.xml файлів
5. **PDF** - Збереження PDF файлів з перейменуванням (Марка + Модель + VIN)
6. **Експорт** - Збереження в Excel файл (`vmd_extractor/data/extract_data/`)

## 📋 Параметри командного рядка

### Головний extractor (`vmd_extractor.py` або `-m vmd_extractor.cli.extractor`):

- `--today` - Завантажити ВМД тільки за поточний день
- `--days N` - Завантажити ВМД за останні N днів
- `--from YYYY-MM-DD` - Початкова дата фільтрації (включно)
- `--to YYYY-MM-DD` - Кінцева дата фільтрації (включно)
- `--no-sort` - Не сортувати повідомлення по даті

### Звіт про ВМД (`-m vmd_extractor.cli.report`):

- `--today` - Звіт за поточний день
- `--days N` - Звіт за останні N днів
- `--from YYYY-MM-DD` - Початкова дата (включно)
- `--to YYYY-MM-DD` - Кінцева дата (включно)

### Обробка розпакованих (`-m vmd_extractor.cli.process_extracted`):

- Не потребує параметрів
- Обробляє всі файли з `vmd_extractor/data/temp_extracted/`

## 🔧 Технічні деталі

- **Асинхронність:** Використовує `asyncio` для паралельної обробки
- **Завантаження:** Послідовне завантаження з затримкою (2 секунди за замовчуванням)
- **Обробка:** Всі файли обробляються паралельно
- **Парсинг:** Всі документи парсяться паралельно
- **Оптимізація:** Звіт про ВМД зберігає UID повідомлень для швидкого завантаження

## 📂 Структура даних

### Вхідні дані:
- Email повідомлення з вкладеннями `.imfx` (ZIP архіви)
- Розмір файлів: 280-320 KB (фільтрується автоматично)
- Відправники: `edecl_vmd1@customs.gov.ua`, `edecl_vmd2@customs.gov.ua`, `edecl_vmd3@customs.gov.ua`

### Вихідні дані:
- **Excel файл** (`vmd_extractor/data/extract_data/vmd_extracted.xlsx`):
  - Всі дані про транспортні засоби
  - Технічні характеристики
  - Фінансові дані
  - Посилання на PDF файли
  
- **PDF файли** (`vmd_extractor/data/pdf/`):
  - Перейменовані: `Марка Модель VIN.pdf`
  - Зберігаються автоматично

### Тимчасові файли:
- `vmd_extractor/data/files/` - Завантажені .imfx файли (видаляються після обробки)
- `vmd_extractor/data/temp_extracted/` - Розпаковані архіви (залишаються для модернізації)

## ⚠️ Важливі примітки

1. **Файл `.env`** - Обов'язковий для роботи. Містить налаштування IMAP та фільтрів.
2. **Віртуальне середовище** - Створюється автоматично при першому запуску.
3. **Завантаження** - Завантажує ВСІ ВМД в діапазоні, без обмеження кількості.
4. **Дублікати** - Автоматично визначаються по SHA256 хешу, не завантажуються повторно.
5. **PDF файли** - Автоматично перейменовуються та зберігаються в окремій папці.

## 🐛 Вирішення проблем

### Помилка підключення до IMAP:
- Перевірте налаштування в `.env` файлі
- Переконайтеся що використовуєте IMAP пароль (не звичайний пароль)

### Файли не завантажуються:
- Перевірте фільтри розміру (MIN_SIZE_KB, MAX_SIZE_KB)
- Перевірте чи є ВМД в діапазоні дат (використайте `--report`)

### Помилки парсингу:
- Перевірте чи файли правильно розпаковані
- Перевірте наявність `doc2.xml` в розпакованих архівах

## 📄 Ліцензія

Внутрішній проект.


Швидкі команди:
# Швидка перевірка за тиждень
python run.py --week

# Місячна вигрузка
python run.py --month

# Вигрузка за поточний місяць (з 1 числа)
python run.py --current-month

# Конкретний період
python run.py --from 2025-10-01 --to 2025-10-31

Мітки:
------------------------------------------------------------------------
Назва                          | Колір        | ID
------------------------------------------------------------------------
Контейнер (Змінний кузов)      | green        | 68d52ea73ee85a752e868b2a
Автомобіль вантажний           | yellow       | 68d52ea73ee85a752e868b29
Сідельний тягач                | red          | 68d52ea73ee85a752e868b2b
Причіп                         | purple       | 68d52ea73ee85a752e868b2c
Напівпричіп                    | blue         | 68d52ea73ee85a752e868b2d
Інше                           | pink         | 691d86f856167c6336a5e992
------------------------------------------------------------------------