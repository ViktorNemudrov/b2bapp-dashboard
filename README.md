# B2BAPP Dashboard

Дашборд проекта мобильного приложения для микробизнеса Билайн.

## Структура

```
public/
  index.html          — Главная страница (разводящая)
  shared.css          — Общие стили
  data/
    data.json         — Данные из Jira + план проекта (обновляется)
  pages/
    gantt.html        — Диаграмма Ганта
    usm.html          — User Story Map
    resources.html    — Ресурсный план (тепловая карта)
    mvp.html          — MVP по кварталам
    scope_dec.html    — Скоуп до 10.12.2026
    risks.html        — Реестр рисков
    assumptions.html  — Реестр допущений
    questions.html    — Открытые вопросы
    stakeholders.html — Стейкхолдеры + RACI
    dependencies.html — Внешние зависимости
    sprints.html      — Бэклог по спринтам
    acceptance.html   — Критерии приёмки MVP
    glossary.html     — Глоссарий
    grooming.html     — Таблица груминга
```

## Обновление данных

Данные в `public/data/data.json` обновляются тремя способами:

1. **По запросу в чате** — сказать Claude: «Обнови данные дашборда из Jira»
2. **Кнопка на сайте** — кнопка «↻ Обновить данные» на главной
3. **Автоматически** — GitHub Actions (2 раза в день, если Jira доступна)

## Деплой

Сайт автоматически деплоится на Vercel при каждом пуше в `main`.

Подключить: Vercel → Import Git Repository → `b2bapp-dashboard`
