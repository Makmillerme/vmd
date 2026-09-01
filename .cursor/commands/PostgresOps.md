# PostgresOps

Single-entry operational command for PostgreSQL + server management.

## VMD Extractor context

This repo is a **Python CLI** using **SQLite** locally. Postgres-ops manages the **server stack** at `/root/apps/PostgressOps`.

| Layer | Technology | Path / name |
|-------|------------|-------------|
| App runtime | Python 3.10+, systemd | `/opt/vmd` |
| App database | SQLite | `vmd_extractor/data/db/vmd_data.sqlite3` |
| Server Postgres | Docker stack | DB `vmd_parser` (optional / future) |

**Default assumption:** PostgresOps tasks are about **stack health**, **backups**, or **future Postgres migration** — not day-to-day VMD pipeline.

## What this command should do

When user asks for PostgresOps actions, execute this sequence:

1. **Inspect**
   - Run health and state checks first.
   - Confirm active server path is `/root/apps/PostgressOps`.
   - Note whether request affects SQLite app (`/opt/vmd`) or Postgres only.
2. **Operate**
   - Perform requested action via MCP tool or `scripts/*.sh`.
3. **Verify**
   - Re-run health checks and verify expected result.
4. **Report**
   - Return concise summary with status and next safe step.

## Supported operation categories

- **Health & diagnostics**
  - `healthcheck_stack`
  - `run_healthcheck`
  - container status, logs, connectivity checks

- **Database lifecycle**
  - list/create/drop databases
  - list/create/drop roles
  - rotate passwords
  - read-only SQL checks (e.g. inspect `vmd_parser`)

- **PgBouncer management**
  - create/update DB mappings
  - reload PgBouncer

- **Backup & restore**
  - trigger backup now
  - confirm backup artifact presence

- **Server/project operations**
  - `run_install`, `run_reinstall`, `run_upgrade`
  - `scripts/server-update.sh`
  - path migration checks (`STACK_DIR`, `SCRIPTS_DIR`, MCP path)

## Safety guardrails

- Ask confirmation before destructive actions:
  - clean reinstall
  - dropping databases/roles (especially `vmd_parser`)
- Never run multiple risky operations in one step.
- Always verify post-operation health.
- Do not conflate SQLite file backups with Postgres stack backups.

## Quick examples

- “PostgresOps health” → full stack healthcheck; mention `vmd_parser` status if relevant.
- “PostgresOps inspect vmd_parser” → `run_sql` on `vmd_parser`, SELECT-only.
- “PostgresOps backup now” → trigger backup; note this backs up **Postgres**, not SQLite at `/opt/vmd`.
- “PostgresOps create db vmd_new” → create role+db, map PgBouncer, verify (only when user requests migration/new module).

## Related docs

- App deploy: [`deploy/README.md`](../deploy/README.md)
- MCP setup: [`.cursor/MCP_SETUP.md`](../MCP_SETUP.md)
- Operator rule: [`postgressops-server-operator.mdc`](../rules/postgressops-server-operator.mdc)
