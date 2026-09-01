#!/usr/bin/env node
/**
 * Декодування: український текст, набраний у EN-розкладці (Windows ЙЦУКЕН ↔ QWERTY).
 *
 * Приклади:
 *   node decode-ukrainian-en-layout.mjs "ghbdsn cdsn"
 *   node decode-ukrainian-en-layout.mjs --no-smart "Ghbdsn!"
 *   echo "хкгт" | node decode-ukrainian-en-layout.mjs --no-smart   # якщо в pipe латиниця
 *   node decode-ukrainian-en-layout.mjs -f ./note.txt
 *   node decode-ukrainian-en-layout.mjs --check
 *
 * Ключі: --smart (за замовч.), --no-smart, -f/--file, --map, --check, -h/--help
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_MAP = path.join(__dirname, "..", "uk-en-layout-map.json");
const VERSION = "2.0.0";

/** @type {Record<string, string> | null} */
let LOWER = null;

function loadMap(mapPath) {
  const raw = fs.readFileSync(mapPath, "utf8");
  const j = JSON.parse(raw);
  if (!j.lower || typeof j.lower !== "object") {
    throw new Error(`Некоректний JSON: очікується поле "lower" у ${mapPath}`);
  }
  return j.lower;
}

/**
 * Латинські слова / токени — не конвертувати в smart-режимі.
 */
const TECH_WORDS = new Set(
  String.raw`
npm npx yarn pnpm git api url uri ssh css html jsx tsx json csv xml svg png jpg gif webp
http https www dev prod src dist lib app web ui ux sql db orm jwt os cpu ram rom gpu
ssd hdd pdf xlsx mcp ide cli cd dir env cwd win mac linux unix bash zsh fish
ps1 cmd exe dll ts js mjs cjs c cpp h rs go py rb php java kt swift dart node react next
vue nuxt redux zustand prisma postgres postgresql mysql sqlite mongodb redis docker k8s argo
eslint prettier vitest jest mocha cypress playwright webpack vite rollup turbopack
import export const let var function return async await typeof void new class extends
true false null undefined NaN Infinity prototype length push pop shift map filter reduce sort
todo fixme bugfix refactor chore docs readme md mdc jsx lang use hook state props ref ctx
install uninstall uninstalling global local latest version update upgrade patch minor major
package packages lock workspace link unlink publish unpublish login logout whoami
add remove rm copy mv ls grep sed awk chmod chown sudo su pwd mkdir rclone scp rsync curl wget
save optional force legacy peer dedupe audit fix fixes fixed fixing unfixed broken build builds
test tests testing spec specs lint lints format formats ci cd github gitlab bitbucket
jenkins travis circle teamcity azure gcp aws cloudflare vercel netlify heroku
studio code cursor vscode neovim emacs intellij powershell terminal console stdin stdout stderr
registry proxy mirror fork clone branch branches merge rebase squash commit commits push pull
stash issue issues pr prs mr draft wip rfc adr lgtm sgtm asap fwiw imo iirc eod eow yolo
if else switch case break continue default try catch throw throws finally instanceof
for while do loop each of in is are was were be been being have has had having
the and or not but nor xor what when where which who whom whose why how
that this these those then than thus thanx thanks plz please ok okay vs per via a an as at by
to from into onto upon over out off up down left right side inner outer end start stop begin
open close load read write edit paste cut undo redo select all find replace
run runs ran running restart pause resume kill abort skip ignore enable disable
on off yes no maybe all none some any each every both few many much more most less least
about above below between among within before after during until unless though although
because since therefore hence yet still also only even just very too can could
should would might must shall will wont dont doesnt didnt isnt arent wasnt werent cant
`.split(/\s+/g).filter(Boolean),
);

function mapChar(ch) {
  if (LOWER[ch] !== undefined) return LOWER[ch];
  const low = ch.toLowerCase();
  if (LOWER[low] === undefined) return ch;
  const mapped = LOWER[low];
  return ch === ch.toUpperCase() && ch !== low ? mapped.toLocaleUpperCase("uk") : mapped;
}

/**
 * @param {string} text
 * @param {{ smart?: boolean }} [opts]
 */
export function decodeLayout(text, opts = {}) {
  const smart = opts.smart !== false;
  if (!smart) {
    return [...text].map(mapChar).join("");
  }

  const out = [];
  let i = 0;
  while (i < text.length) {
    const slice = text.slice(i);
    const m = slice.match(/^([a-zA-Z]{2,})/);
    if (m) {
      const word = m[1];
      const lowerW = word.toLowerCase();
      if (TECH_WORDS.has(lowerW)) {
        out.push(word);
        i += word.length;
        continue;
      }
      let converted = "";
      let allMappable = true;
      for (const ch of word) {
        const low = ch.toLowerCase();
        if (LOWER[low] === undefined && /[a-zA-Z]/.test(ch)) {
          allMappable = false;
          break;
        }
        converted += mapChar(ch);
      }
      if (allMappable && /[a-zA-Z]/.test(word)) {
        out.push(converted);
        i += word.length;
        continue;
      }
    }
    const cp = text.codePointAt(i);
    if (cp === undefined) break;
    const ch = String.fromCodePoint(cp);
    out.push(mapChar(ch));
    i += ch.length;
  }
  return out.join("");
}

function printHelp() {
  process.stdout.write(`decode-ukrainian-en-layout.mjs v${VERSION}

Український текст, набраний у EN-розкладці → відновлення кирилиці (див. uk-en-layout-map.json).

Використання:
  node decode-ukrainian-en-layout.mjs [опції] [\"текст\"]
  echo латиниця | node decode-ukrainian-en-layout.mjs [опції]

Опції:
  --smart          Режим за замовчуванням: не чіпати технічні англ. слова (npm, import…).
  --no-smart       Підмінити всі символи з таблиці (чиста «забув розкладку»).
  -f, --file PATH  Прочитати вхід з файлу (UTF-8).
  --map PATH       Альтернативний JSON з полем \"lower\".
  --check          Перевірка: ghbdsn cdsn → «привіт світ»; код виходу 0/1.
  -h, --help       Ця довідка.

Змінна середовища: UK_LAYOUT_MAP — шлях до JSON (пріоритет над --map за замовчуванням).

`);
}

function runSelfTest(mapPath) {
  LOWER = loadMap(mapPath);
  const a = decodeLayout("ghbdsn cdsn", { smart: false });
  const b = decodeLayout("vjlthyspeq", { smart: false });
  const ok = a.trim() === "привіт світ" && b.trim() === "модернізуй";
  if (!ok) {
    process.stderr.write(
      `SELFTEST FAIL: expected "привіт світ" and "модернізуй", got:\n  ${JSON.stringify(a)}\n  ${JSON.stringify(b)}\n`,
    );
    process.exit(1);
  }
  process.stdout.write("OK: self-test ghbdsn cdsn → привіт світ; vjlthyspeq → модернізуй\n");
  process.exit(0);
}

function parseArgs(argv) {
  const out = {
    help: false,
    check: false,
    smart: true,
    file: null,
    map: null,
    positional: [],
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-h" || a === "--help") out.help = true;
    else if (a === "--check") out.check = true;
    else if (a === "--no-smart") out.smart = false;
    else if (a === "--smart") out.smart = true;
    else if (a === "-f" || a === "--file") {
      out.file = argv[++i];
      if (!out.file) throw new Error("Отсутній шлях після -f/--file");
    } else if (a === "--map") {
      out.map = argv[++i];
      if (!out.map) throw new Error("Отсутній шлях після --map");
    } else if (!a.startsWith("-")) out.positional.push(a);
    else throw new Error(`Невідомий аргумент: ${a} (використай -h)`);
  }
  return out;
}

function readStdinSync() {
  try {
    return fs.readFileSync(0, "utf8");
  } catch {
    return "";
  }
}

function main() {
  const argv = process.argv.slice(2);
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (e) {
    process.stderr.write(String(e.message || e) + "\n");
    process.exit(2);
  }

  if (opts.help) {
    printHelp();
    process.exit(0);
  }

  const mapPath = path.resolve(opts.map || process.env.UK_LAYOUT_MAP || DEFAULT_MAP);

  if (opts.check) {
    runSelfTest(mapPath);
  }

  LOWER = loadMap(mapPath);

  let input = opts.positional.join(" ");

  if (opts.file) {
    input = fs.readFileSync(path.resolve(opts.file), "utf8");
  } else if (!input) {
    if (!process.stdin.isTTY) {
      input = readStdinSync();
    }
  }

  input = input.replace(/^\uFEFF/, "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");

  const decoded = decodeLayout(input, { smart: opts.smart });
  process.stdout.write(decoded);
  if (!decoded.endsWith("\n")) process.stdout.write("\n");
}

const isDirectRun =
  typeof process.argv[1] === "string" &&
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (isDirectRun) main();
