# uk-layout

Користувач міг набрати **українською**, але з **EN-розкладкою** (латиниця замість кирилиці).

## Дії

1. Прочитай правило: `.cursor/rules/ukrainian-wrong-keyboard-layout.mdc`
2. Декодуй фразу через Node (UTF-8, без PowerShell для тіла запитів):
   ```powershell
   cd d:\Project\mtruck\vmd
   node .cursor/scripts/decode-ukrainian-en-layout.mjs "ВСТАВ_ТЕКСТ_З_ЧАТУ"
   ```
   За потреби повний прохід по таблиці: додай **`--no-smart`**.

3. Відповідай по **розшифрованому** змісту; таблиця символів: `.cursor/uk-en-layout-map.json`.

Ця команда доступна як **/uk-layout**.
