# audit

Перевірка **Python CLI VMD Extractor** на проблеми **async/I/O**, **SQLite**, **Trello API**, **обробку помилок** для поточного контексту або змін.

## Що перевіряти

1. **Async:** чи немає блокуючого I/O в async-функціях (`input()`, sync sqlite, sync file I/O без `asyncio.to_thread`).
2. **SQLite:** транзакції, `row_factory`, UNIQUE constraints, міграції схеми в `VMDDatabase`.
3. **Trello:** HTTP 414 (payload у body), rate limits, `CancelledError` vs user cancel.
4. **Pipeline:** orchestrator flow, cleanup temp files, duplicate SHA256 handling.
5. **Config:** `.env` fallbacks, timezone, label mapping.

## Що зробити

1. Якщо є логи терміналу — переглянути stack trace / exit code.
2. Ревʼю коду змінених модулів через Serena (`find_symbol`, `find_referencing_symbols`).
3. Звітуй знайдене та пропозиції; критичні правки — через **`/serena`** у **Agent**.

## Не застосовується

- Next.js hydration, RSC, `"use client"` — цей проєкт не має frontend.

Ця команда доступна в чаті як /audit
