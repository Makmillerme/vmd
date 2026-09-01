---
name: vmd-workflow
description: Standard workflow for VMD Extractor Python CLI development using Serena MCP for code, postgres-ops for server DB stack, Trello MCP for board ops. Use when working on pipeline, CLI, deploy, or integrations.
---

# VMD Development Workflow

## Command pipeline

| Phase | Command | Role |
|-------|---------|------|
| Planning | `/plan` + Plan mode | sequential-thinking for complex changes |
| Implementation | `/serena` in Agent | `activate_project` → `d:\Project\mtruck\vmd` |
| Docs | `/docs` | Python libs from `requirements.txt` |
| Quality | `/audit` | async, SQLite, Trello, error handling |
| Server Postgres | `/PostgresOps` | stack health, backups — **not** app SQLite |
| Trello | `/trello` | board/card operations |

## Serena workflow

1. `activate_project` with `vmd`
2. `find_symbol` / `get_symbols_overview` before edits
3. `replace_symbol_body` or `replace_content` for changes
4. `write_memory` after significant work

## Key modules

```
vmd_extractor/
├── core/          orchestrator, downloader, processor, parser, database, exporter
├── utils/         xml_parser, data_extractor, trello_integration
├── cli/           menus, run entrypoints
└── config.py      .env loading
```

Entry points: `run.py`, `run_auto.py` (scheduled pipeline + weekly email).

## Deploy (server)

- Path: `/opt/vmd`
- Schedule: 08/12/16/20 pipeline, Monday 09:00 weekly report
- Docs: `deploy/README.md`, systemd units in `deploy/systemd/`

## Database rule

- **App runtime:** SQLite only
- **Postgres on server:** operational via postgres-ops; do not wire into CLI unless user requests migration

## Skills map

| Task | Skill |
|------|-------|
| SQLite, schema, export | `vmd-data` |
| Trello sync, labels | `bot-engineer` / trello command (API via aiohttp in code) |
| Complex refactor | `strategic-planning` + `/plan` |

## Anti-patterns

- Using Next.js/shadcn skills for this repo
- Running postgres-ops DDL for "fixing" local SQLite issues
- Starting `run_auto.py` daemon without user request
