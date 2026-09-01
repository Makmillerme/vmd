# plan

Планування завжди в **парі з режимом Plan** у Composer (не лише текстом у Agent).

## Що зробити

1. Увімкни **Plan** у селекторі режиму Composer (або `SwitchMode` → `plan`, якщо доступно).
2. Залучи **sequential-thinking MCP** (`user-sequential-thinking`, tool `sequentialthinking`): аналіз задачі, ризики, залежності, поетапний план, за потреби альтернативи.
3. Узгодь напрям з користувачем; **не** масово змінюй код, поки триває Plan.
4. **Після узгодження — закрий планування:** перемкни Composer на **Agent**, коротко підсумуй план, переходь до реалізації з **`/serena`**.

Детальніше: [`.cursor/rules/senior-agent-workflow.mdc`](../rules/senior-agent-workflow.mdc).

Ця команда доступна в чаті як /plan
