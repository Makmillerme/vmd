#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Створення карток Trello для вказаних VIN (без меню)."""

import argparse
import asyncio
import sys

from vmd_extractor.core.orchestrator import VMDOrchestrator


def parse_args():
    parser = argparse.ArgumentParser(
        description="Синхронізувати вказані VIN з Trello (створити картки, якщо немає)."
    )
    parser.add_argument(
        "vins",
        nargs="+",
        help="Один або кілька VIN (пробіли або коми)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    vins = []
    for part in args.vins:
        vins.extend(p.strip() for p in part.split(",") if p.strip())
    if not vins:
        print("VIN не вказано.")
        return 1

    orchestrator = VMDOrchestrator()
    await orchestrator.database.initialize()
    print("VIN для синхронізації:", ", ".join(vins))
    await orchestrator.sync_trello_for_vins(vins)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nСкасовано.")
        sys.exit(1)
