# init

Онбординг **VMD Extractor**: перевір структуру проєкту, `.env`, venv, SQLite БД, опційно systemd на сервері.

## Checklist

- [ ] Python 3.10+, `pip install -r requirements.txt`
- [ ] `.env` з IMAP, Trello, SMTP (див. README)
- [ ] SQLite: `vmd_extractor/data/db/vmd_data.sqlite3` створюється при першому запуску
- [ ] Тест: `python run.py` або `python run_auto.py --once`
- [ ] Сервер (опційно): `/opt/vmd`, systemd timers — `deploy/README.md`
- [ ] Postgres: **не обовʼязковий**; stack через `/PostgresOps` лише для серверного обслуговування

## Не питати про

- Prisma / Payload / Next.js / Telegram bot — не частина цього CLI.

Ця команда доступна в чаті як /init
