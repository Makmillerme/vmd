#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автономний запуск VMD Extractor (для серверів / cron / systemd).
Запускає pipeline у автоматичному режимі: діапазон дат береться з історії БД.
Розклад (daemon-режим): 08:00, 12:00, 16:00, 20:00 щодня; понеділок 09:00 — розсилка.
На сервері рекомендується systemd timer (див. deploy/systemd/).
"""

import argparse
import asyncio
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, time as dt_time
from pathlib import Path
from typing import List, Optional, Tuple

from run import check_env_file, get_runtime_python
from vmd_extractor.config import LOCAL_TZ

# Щоденна перевірка ВМД (4 рази)
PIPELINE_RUN_TIMES: List[dt_time] = [
    dt_time(8, 0),
    dt_time(12, 0),
    dt_time(16, 0),
    dt_time(20, 0),
]
# Тижнева розсилка — понеділок
WEEKLY_REPORT_TIME = dt_time(9, 0)


def _parse_iso_date(iso_value: Optional[str]) -> Optional[datetime]:
    if not iso_value:
        return None
    try:
        return datetime.fromisoformat(iso_value)
    except ValueError:
        return None


async def _fetch_db_window() -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
    from vmd_extractor.core.database import VMDDatabase
    from vmd_extractor.config import DB_PATH

    db = VMDDatabase(DB_PATH)
    await db.initialize()
    last_window = await db.get_last_successful_window()
    last_download = await db.get_last_download_timestamp()
    return last_window, last_download


def determine_auto_range() -> Tuple[date, date]:
    """
    Визначає автоматичний діапазон дат:
    - старт = дата останнього успішного запуску (або останнього завантаженного файлу)
    - кінець = поточна дата
    """
    last_window, last_download = asyncio.run(_fetch_db_window())

    now_local = datetime.now(LOCAL_TZ)
    start_dt = None

    if last_window:
        window_start_iso, window_end_iso = last_window
        # Перевага останньому кінцю, інакше старту
        start_dt = _parse_iso_date(window_end_iso) or _parse_iso_date(window_start_iso)

    if not start_dt and last_download:
        start_dt = _parse_iso_date(last_download)

    if not start_dt:
        start_dt = now_local
    else:
        if start_dt.tzinfo:
            start_dt = start_dt.astimezone(LOCAL_TZ)
        else:
            start_dt = start_dt.replace(tzinfo=LOCAL_TZ)

    start_date = start_dt.date()
    end_date = now_local.date()
    if end_date < start_date:
        end_date = start_date
    return start_date, end_date


def parse_args():
    parser = argparse.ArgumentParser(description="Autonomous runner for VMD Extractor.")
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="Перевірити останній запуск (для systemd health-check) і вийти.",
    )
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=12,
        help="Максимальний вік успішного запуску (у годинах) для health-check.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Запустити pipeline один раз і вийти (без розкладу).",
    )
    parser.add_argument(
        "--weekly-report",
        action="store_true",
        help="Відправити email-звіт ВМД за минулий тиждень (без інтерактивного підтвердження).",
    )
    return parser.parse_args()


async def _fetch_last_sync_run_details():
    from vmd_extractor.core.database import VMDDatabase
    from vmd_extractor.config import DB_PATH

    db = VMDDatabase(DB_PATH)
    await db.initialize()
    return await db.get_last_sync_run()


def perform_health_check(max_age_hours: int):
    last_run = asyncio.run(_fetch_last_sync_run_details())
    if not last_run:
        print("FAIL: Не знайдено жодного запису в sync_runs.")
        sys.exit(2)

    status = last_run.get("status")
    finished_at = _parse_iso_date(last_run.get("finished_at"))
    if status != "success":
        print(f"FAIL: Останній запуск завершився зі статусом: {status}")
        sys.exit(3)
    if not finished_at:
        print("FAIL: Не вдалося визначити час завершення останнього запуску.")
        sys.exit(3)

    finished_local = finished_at.astimezone(LOCAL_TZ)
    age = datetime.now(LOCAL_TZ) - finished_local
    if age > timedelta(hours=max_age_hours):
        print(
            f"FAIL: Останній успішний запуск був {finished_local} "
            f"(понад {max_age_hours} годин тому)."
        )
        sys.exit(4)

    print(
        f"OK: Останній запуск успішний ({finished_local}), "
        f"files_downloaded={last_run.get('files_downloaded')}."
    )
    sys.exit(0)


def run_pipeline_once():
    """Запускає pipeline один раз"""
    check_env_file()
    venv_python = get_runtime_python()

    auto_from, auto_to = determine_auto_range()
    print(f"Автономний діапазон: від {auto_from.isoformat()} до {auto_to.isoformat()}")
    print("=" * 60)
    print("Запуск автоматичного конвеєра...\n")

    extractor_script = Path("vmd_extractor") / "cli" / "extractor.py"
    if not extractor_script.exists():
        print(f"Помилка: файл {extractor_script} не знайдено!")
        return 1

    cmd = [
        str(venv_python),
        str(extractor_script),
        "--from",
        auto_from.isoformat(),
        "--to",
        auto_to.isoformat(),
    ]

    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except KeyboardInterrupt:
        print("\n\nОперацію скасовано користувачем")
        return 1
    except Exception as e:
        print(f"\n\nПомилка запуску автоматичного режиму: {e}")
        return 1


def run_weekly_report_once() -> int:
    """Відправляє тижневий звіт ВМД за минулий тиждень (без меню)."""
    check_env_file()

    from vmd_extractor.cli.menus.utils import get_previous_week_range
    from vmd_extractor.cli.menus.mailing import send_vmd_report_email

    week_from, week_to = get_previous_week_range()
    print("=" * 60)
    print("VMD EXTRACTOR — тижнева розсилка")
    print(f"Період: {week_from} — {week_to}")
    print("=" * 60)

    try:
        success = asyncio.run(
            send_vmd_report_email(
                week_from,
                week_to,
                "Звіт ВМД за минулий тиждень",
            )
        )
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n\nОперацію скасовано користувачем")
        return 1
    except Exception as e:
        print(f"\n\nПомилка розсилки: {e}")
        return 1


def _format_times(times: List[dt_time]) -> str:
    return ", ".join(t.strftime("%H:%M") for t in sorted(times))


def get_next_scheduled_event(
    pipeline_times: List[dt_time],
    weekly_report_time: dt_time,
) -> Tuple[datetime, str]:
    """
    Наступна подія: pipeline або weekly_report (понеділок).
    Повертає (datetime, 'pipeline' | 'weekly_report').
    """
    now = datetime.now(LOCAL_TZ)
    today = now.date()
    candidates: List[Tuple[datetime, str]] = []

    for target_time in pipeline_times:
        for day_offset in (0, 1):
            day = today + timedelta(days=day_offset)
            dt = datetime.combine(day, target_time).replace(tzinfo=LOCAL_TZ)
            if dt > now:
                candidates.append((dt, "pipeline"))

    for day_offset in range(8):
        day = today + timedelta(days=day_offset)
        if day.weekday() != 0:  # Monday
            continue
        dt = datetime.combine(day, weekly_report_time).replace(tzinfo=LOCAL_TZ)
        if dt > now:
            candidates.append((dt, "weekly_report"))
            break

    if not candidates:
        tomorrow = today + timedelta(days=1)
        first_pipeline = min(pipeline_times)
        return (
            datetime.combine(tomorrow, first_pipeline).replace(tzinfo=LOCAL_TZ),
            "pipeline",
        )

    return min(candidates, key=lambda x: x[0])


def run_scheduled_mode():
    """Daemon-режим: pipeline 4×/день + розсилка по понеділках о 09:00."""
    print("=" * 60)
    print("VMD EXTRACTOR - Автономний режим з розкладом")
    print("=" * 60)
    print(f"Pipeline: {_format_times(PIPELINE_RUN_TIMES)} щодня")
    print(f"Розсилка: понеділок о {WEEKLY_REPORT_TIME.strftime('%H:%M')}")
    print("Режим: фоновий (натисніть Ctrl+C для зупинки)")
    print("=" * 60)

    while True:
        next_run, event_type = get_next_scheduled_event(
            PIPELINE_RUN_TIMES, WEEKLY_REPORT_TIME
        )
        wait_seconds = (next_run - datetime.now(LOCAL_TZ)).total_seconds()

        label = "pipeline" if event_type == "pipeline" else "тижнева розсилка"
        print(f"\nНаступна подія ({label}): {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Очікування: {int(wait_seconds // 3600)} год. {int((wait_seconds % 3600) // 60)} хв.")

        try:
            time.sleep(wait_seconds)
        except KeyboardInterrupt:
            print("\n\nРоботу зупинено користувачем")
            sys.exit(0)

        print(f"\n{'='*60}")
        print(f"Запуск ({label}): {datetime.now(LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        if event_type == "weekly_report":
            exit_code = run_weekly_report_once()
        else:
            exit_code = run_pipeline_once()

        if exit_code != 0:
            print(f"\nПомилка виконання (код: {exit_code})")

        print("\nЗавершено. Очікування наступної події...\n")


def main():
    args = parse_args()
    if args.health_check:
        perform_health_check(args.max_age_hours)
        return

    if args.weekly_report:
        sys.exit(run_weekly_report_once())

    if args.once:
        sys.exit(run_pipeline_once())

    run_scheduled_mode()


if __name__ == "__main__":
    main()

