---
name: vmd-data
description: Manages VMD Extractor data layer — SQLite (primary), schema in VMDDatabase, export to Excel. Documents relationship to server Postgres (vmd_parser via postgres-ops). Use when working with databases, migrations, backups, or data models in this CLI.
---

# VMD Data Layer

## Primary database: SQLite

| Item | Value |
|------|-------|
| File | `vmd_extractor/data/db/vmd_data.sqlite3` |
| Config | `VMD_DB_FILENAME` in `.env`, default in `config.py` |
| Access | `VMDDatabase` (`vmd_extractor/core/database.py`), `aiosqlite` |
| Tables | `email_messages`, `processed_files`, `vehicles`, `sync_runs`, `trello_cards`, `trello_labels`, `briefs` |

### Workflow

1. Schema changes → edit `VMDDatabase` init/migration logic in `database.py`.
2. Always use transactions for multi-table writes (`persist_pipeline_run`).
3. Backup before destructive ops: copy `.sqlite3` file.
4. Export: `ExcelExporter` reads from SQLite → `data/extract_data/`.

### Anti-patterns

- Do not assume PostgreSQL connection exists in app code.
- Do not run DDL on server `vmd_parser` without explicit user request and backup.

## Server PostgreSQL (optional / separate)

Managed by **user-postgres-ops** MCP, not by VMD CLI.

| Item | Value |
|------|-------|
| Stack | `/root/apps/PostgressOps` |
| DB name | `vmd_parser` |
| Status | Exists on server; **current CLI does not connect** |

Use postgres-ops for:
- Stack health, backups
- Read-only inspection (`run_sql`, SELECT only)
- Future migration SQLite → Postgres (requires user approval + plan)

See: [`.cursor/rules/postgressops-server-operator.mdc`](../../rules/postgressops-server-operator.mdc)

## When user asks to "use Postgres"

1. Confirm intent: replace SQLite, dual-write, or read-only analytics?
2. Run `/plan` for migration scope.
3. Backup both SQLite file and `run_backup_now` on Postgres stack.
4. Do not provision/drop `vmd_parser` without confirmation.

## Checklist

- [ ] Identified SQLite vs Postgres scope
- [ ] Schema change reviewed in `database.py`
- [ ] Backup strategy noted (file copy or postgres-ops)
- [ ] No secrets in repo
