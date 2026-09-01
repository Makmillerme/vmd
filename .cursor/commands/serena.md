# serena

Використовуй у **режимі Agent** після **закриття Plan** (узгоджений план у [`/plan`](plan.md)). Усі завдання з коду через **Serena MCP** (user-serena) — не вручну через search_replace/write, крім fallback з [`serena-editing.mdc`](../rules/serena-editing.mdc).

## Перед початком

1. **Активуй проєкт:** `call_mcp_tool` → server `user-serena`, tool `activate_project`, args `{"project": "d:\\Project\\mtruck\\vmd"}`
2. Проєкт: `vmd` (шлях: `d:\Project\mtruck\vmd`)

## Доступні інструменти (активні)

| Інструмент | Призначення |
|------------|-------------|
| `activate_project` | Активація проєкту (vmd) |
| `find_symbol` | Пошук символів за name_path_pattern |
| `get_symbols_overview` | Огляд символів у файлі |
| `replace_symbol_body` | Замінити тіло символу |
| `insert_after_symbol` / `insert_before_symbol` | Вставка коду |
| `replace_content` | Заміна патерну (literal або regex) |
| `find_referencing_symbols` | Знайти посилання на символ |
| `search_for_pattern` | Пошук патерну в проєкті |
| `read_file` / `create_text_file` | Читання/запис файлів |
| `write_memory` | Записати в `.serena/memories/` |

## Workflow

1. **Пошук:** `find_symbol` або `get_symbols_overview`
2. **Заміна:** `replace_symbol_body` або `replace_content`
3. **Після змін:** `write_memory` з memory_name та content

Ця команда доступна в чаті як /serena
