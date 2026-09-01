
Створіть форк репозиторію
Копіювати
git clone https://github.com/shadcn-ui/ui.git
Створити нову гілку
Копіювати
git checkout -b username/my-new-block
Встановлення залежностей
Копіювати
pnpm install
Запустіть сервер розробки
Копіювати
pnpm www:dev
Додати блок
Блок може бути окремим компонентом (наприклад, варіацією компонента інтерфейсу користувача) або складним компонентом (наприклад, панеллю інструментів) з кількома компонентами, перехопленнями та утилітами.

Створити новий блок
Створіть нову папку в apps/www/registry/new-york/blocksкаталозі. Переконайтеся, що назва папки вказана з використанням літер kebab-case та розташована під new-york.

Копіювати
apps
└── www
    └── registry
        └── new-york
            └── blocks
                └── dashboard-01
Примітка: Скрипт збірки подбає про створення блоку для defaultстилю.

Додайте файли блоків
Додайте свої файли до папки блоку. Ось приклад блоку зі сторінкою, компонентами, хуками та утилітами.

Копіювати
dashboard-01
└── page.tsx
└── components
    └── hello-world.tsx
    └── example-card.tsx
└── hooks
    └── use-hello-world.ts
└── lib
    └── format-date.ts
Примітка: Ви можете почати з одного файлу та додати більше файлів пізніше.

Додайте свій блок до реєстру
Додайте визначення вашого блоку доregistry-blocks.tsx
Щоб додати блок до реєстру, вам потрібно додати визначення блоку до registry-blocks.ts.

Це відповідає схемі реєстру за адресою https://ui.shadcn.com/schema/registry-item.json .

apps/www/registry/registry-blocks.tsx
Копіювати
export const blocks = [
  // ...
  {
    name: "dashboard-01",
    author: "shadcn (https://ui.shadcn.com)",
    title: "Dashboard",
    description: "A simple dashboard with a hello world component.",
    type: "registry:block",
    registryDependencies: ["input", "button", "card"],
    dependencies: ["zod"],
    files: [
      {
        path: "blocks/dashboard-01/page.tsx",
        type: "registry:page",
        target: "app/dashboard/page.tsx",
      },
      {
        path: "blocks/dashboard-01/components/hello-world.tsx",
        type: "registry:component",
      },
      {
        path: "blocks/dashboard-01/components/example-card.tsx",
        type: "registry:component",
      },
      {
        path: "blocks/dashboard-01/hooks/use-hello-world.ts",
        type: "registry:hook",
      },
      {
        path: "blocks/dashboard-01/lib/format-date.ts",
        type: "registry:lib",
      },
    ],
    categories: ["dashboard"],
  },
]
Обов’язково додайте назву, опис, тип, залежності реєстру, залежності, файли та категорії. Ми розглянемо кожен із них детальніше в документації схеми (буде доступна найближчим часом).

Запустіть скрипт збірки
Копіювати
pnpm registry:build
Примітка: вам не потрібно запускати цей скрипт для кожної зміни. Вам потрібно запускати його лише під час оновлення визначення блоку.

Перегляньте свій блок
Після завершення скрипта збірки ви можете переглянути свій блок за адресою http://localhost:3333/blocks/[CATEGORY]або переглянути його на весь екран за адресою http://localhost:3333/view/styles/new-york/dashboard-01.

Попередній перегляд блоку
Зберіть свій блок
Тепер ви можете створити свій блок, редагуючи файли в папці блоку та переглядаючи зміни у браузері.

Якщо ви додаєте більше файлів, обов'язково додайте їх до filesмасиву у визначенні блоку.

Опублікуйте свій блок
Як тільки ви будете готові опублікувати свій блок, ви можете надіслати запит на зняття (pull request) до основного репозиторію.

Запустіть скрипт збірки
Копіювати
pnpm registry:build
Зробіть знімок екрана
Копіювати
pnpm registry:capture
Примітка: Якщо ви вже запускали скрипт захоплення раніше, можливо, вам доведеться видалити наявні знімки екрана (як світлі, так і темні) та apps/www/public/r/styles/new-yorkзнову запустити скрипт.

Надіслати запит на зняття
Зафіксуйте зміни та надішліть запит на зняття змін до основного репозиторію.

Ваш блок буде перевірено та об'єднано. Після об'єднання він буде опублікований на вебсайті та доступний для встановлення через CLI.

Категорії
Ця categoriesвластивість використовується для впорядкування вашого блоку в реєстрі.

Додати категорію
Якщо вам потрібно додати нову категорію, ви можете зробити це, додавши її до registryCategoriesмасиву в apps/www/registry/registry-categories.ts.

apps/www/registry/registry-categories.ts
Копіювати
export const registryCategories = [
  // ...
  {
    name: "Input",
    slug: "input",
    hidden: false,
  },
]
Керівні принципи
Ось деякі рекомендації, яких слід дотримуватися під час внесення вкладу в бібліотеку блоків.

Для визначення блоку необхідні такі властивості: name, description, type, files, та categories.
Обов’язково перелічіть усі залежності реєстру у файлі registryDependencies. Залежність реєстру – це назва компонента в реєстрі, наприклад input, button, card, тощо.
Обов'язково перелічіть усі залежності у файлі dependencies. Залежність — це назва пакета в реєстрі, наприклад zod, sonner, тощо.
Якщо ваш блок має сторінку (необов'язково), вона має бути першим записом у filesмасиві та мати targetвластивість. Це допомагає CLI розмістити сторінку у правильному місці для маршрутизації на основі файлів.
Імпорт завжди повинен використовувати @/registryшлях, наприклад.import { Input } from "@/registry/new-york/input"