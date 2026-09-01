# Docker deploy (VMD Extractor)

Path on server: `/root/apps/vmd` (or your `apps/` layout).

## Quick start

```bash
cd /root/apps/vmd
git clone https://github.com/Makmillerme/vmd.git .
cp .env.example .env
nano .env   # IMAP, Trello, SMTP, EMAIL

docker compose up -d --build
docker compose logs -f vmd
```

## Commands (override entrypoint)

```bash
# One pipeline run
docker compose run --rm vmd once

# Weekly email report
docker compose run --rm vmd weekly-report

# Health check (last successful sync within N hours)
docker compose run --rm -e MAX_AGE_HOURS=8 vmd health-check
```

## Volumes

| Volume | Mount | Purpose |
|--------|-------|---------|
| `vmd_data` | `/app/vmd_extractor/data` | SQLite, PDF, files |
| `vmd_logs` | `/app/vmd_logs` | Logs |

Backup: `docker run --rm -v vmd_vmd_data:/data -v $(pwd):/backup alpine tar czf /backup/vmd-data-$(date +%F).tar.gz -C /data .`

## Schedule (default `daemon`)

Same as `run_auto.py`: **08:00, 12:00, 16:00, 20:00** pipeline; **Monday 09:00** weekly report.

Alternative: host **cron** instead of daemon:

```cron
0 8,12,16,20 * * * cd /root/apps/vmd && docker compose run --rm vmd once
0 9 * * 1 cd /root/apps/vmd && docker compose run --rm vmd weekly-report
```

Then run container idle or use `docker compose up` only on cron.

## systemd (without Docker)

See [`../README.md`](../README.md) — units in `deploy/systemd/` for `/opt/vmd` + venv.
