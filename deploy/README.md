# Деплой VMD Extractor

**Рекомендовано:** Docker у `/root/apps/vmd` — див. [`docker/README.md`](docker/README.md).

Нижче — альтернатива через systemd + venv (`/opt/vmd`).

## Розклад

| Подія | Час | Команда |
|-------|-----|---------|
| Перевірка ВМД | **08:00, 12:00, 16:00, 20:00** щодня | `run_auto.py --once` |
| Email-розсилка | **понеділок 09:00** | `run_auto.py --weekly-report` |

## Передумови

- Ubuntu 22.04+ (або інший Linux з systemd)
- Python 3.10+
- Заповнений `.env` (IMAP, Trello, SMTP, `EMAIL=...`)

> **База даних:** додаток використовує **SQLite** (`vmd_extractor/data/db/vmd_data.sqlite3`).
> PostgreSQL на сервері (`vmd_parser` тощо) — окремий стек; для цього CLI Postgres **не обов'язковий**.

## Швидке встановлення

```bash
# 1. Клон / копія проєкту
sudo mkdir -p /opt/vmd
sudo chown $USER:$USER /opt/vmd
rsync -av --exclude venv --exclude 'vmd_extractor/data/files' ./ /opt/vmd/

# 2. venv та залежності
cd /opt/vmd
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# 3. .env (скопіюйте з локальної машини)
nano /opt/vmd/.env

# 4. Тестовий запуск
./venv/bin/python run_auto.py --once
./venv/bin/python run_auto.py --weekly-report   # опційно

# 5. systemd (відредагуйте WorkingDirectory якщо шлях інший)
sudo cp deploy/systemd/vmd-extractor.service /etc/systemd/system/
sudo cp deploy/systemd/vmd-extractor.timer /etc/systemd/system/
sudo cp deploy/systemd/vmd-mailing.service /etc/systemd/system/
sudo cp deploy/systemd/vmd-mailing.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now vmd-extractor.timer
sudo systemctl enable --now vmd-mailing.timer
```

## Перевірка

```bash
systemctl list-timers | grep vmd
journalctl -u vmd-extractor.service -n 50
journalctl -u vmd-mailing.service -n 50
/opt/vmd/venv/bin/python run_auto.py --health-check --max-age-hours 8
```

## Ручний запуск

```bash
sudo systemctl start vmd-extractor.service    # одна перевірка ВМД
sudo systemctl start vmd-mailing.service      # розсилка за минулий тиждень
```

## Daemon-режим (альтернатива timer)

Якщо не хочете systemd timer, можна один long-running процес:

```bash
./venv/bin/python run_auto.py
```

(той самий розклад: 4× pipeline + понеділок 09:00)
