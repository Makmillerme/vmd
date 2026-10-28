#!/bin/sh
set -e

cd /app

case "${1:-daemon}" in
  once)
    exec python run_auto.py --once
    ;;
  weekly-report)
    exec python run_auto.py --weekly-report
    ;;
  health-check)
    exec python run_auto.py --health-check --max-age-hours "${MAX_AGE_HOURS:-8}"
    ;;
  sync-vins)
    shift
    exec python vmd_extractor/cli/sync_trello_vins.py "$@"
    ;;
  daemon)
    exec python run_auto.py
    ;;
  shell)
    exec sh
    ;;
  *)
    exec python "$@"
    ;;
esac
