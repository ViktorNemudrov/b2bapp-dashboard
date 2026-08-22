# Формат сырья для `build_dashboard.py` (режим `gantt`)

Эти файлы собирает **Claude в сессии** через браузер (Jira/Confluence) и отдаёт
Виктору. Claude Code кладёт их рядом со скриптом и запускает билдер. Никакой
обработки в браузере — только выгрузка «как есть». Вся логика — в билдере.

---

## 1. `jira_dump.json` — сырая выгрузка Jira

Просто склеенные страницы ответа `GET /rest/api/2/search` (все типы: 3, 20600,
10600, 10500) с нужными полями. Пагинация до `startAt ≥ total`. Кириллицу в JQL
не использовать. Собирается браузерным скиллом `b2bapp-jira` (НЕ по API —
через SPA-вкладку btask, см. скилл).

```json
{
  "collectedAt": "2026-08-21T14:00:00+03:00",
  "total": 620,
  "issues": [
    {
      "key": "B2BAPP-3",
      "fields": {
        "issuetype":   {"id": "3", "name": "Задача"},
        "summary":     "[ORG] Уточнение архитектурной развилки",
        "status":      {"name": "Завершена"},
        "assignee":    {"name": "LPalchikov", "key": "..."},
        "created":     "2026-02-09T10:00:00.000+0300",
        "resolutiondate": "2026-06-09T12:00:00.000+0300",
        "duedate":     null,
        "updated":     "2026-06-09T12:00:00.000+0300",
        "labels":      [],
        "timetracking": {"originalEstimateSeconds": 75600, "timeSpentSeconds": 0},
        "timespent":   0,
        "customfield_10901": "B2BAPP-2",     // Epic Link (у стори)
        "customfield_10903": null,           // Epic Name (у эпика)
        "issuelinks": [
          {"type": {"name": "Part", "inward": "is part of", "outward": "has part"},
           "inwardIssue": {"key": "B2BAPP-2"},      // история
           "outwardIssue": {"key": "B2BAPP-3"}}     // задача
        ]
      }
    }
  ]
}
```

**Что билдер вытащит сам (в браузере НЕ считать):** тип (по issuetype.id),
роль задачи (префикс `[XX]`), приоритет (числовой префикс стори), связь
task→story (Part), story→epic (customfield_10901), часы (сек/3600),
MVP-фильтр (labels содержит `mvp`), вакантные (summary содержит «вакантн»).

**Минимум обязательных полей:** `key`, `issuetype.id`, `summary`, `status.name`,
`created`, `resolutiondate`, `labels`, `timetracking`, `customfield_10901`,
`issuelinks`. Остальное — по возможности, билдер переживёт отсутствие.

**Фактический старт (опционально, дорого):** если для задач «В работе»/
«Завершена» выгружен changelog — можно добавить `"actualStart": "2026-07-01"`
в объект `fields`. Не выгружено — билдер возьмёт `created`. Не гнать changelog
по всем задачам без нужды.

---

## 2. `team_dump.json` — страница «Команда» (Confluence 1562745210)

Собирается **на каждом `gantt`-прогоне** (Виктор: состав меняется, BA уже
сменился со Смирнова на Клейменову). Одна страница, дёшево. Формат — тот же,
что секция `team` в data.json:

```json
{
  "collectedAt": "2026-08-21T14:00:00+03:00",
  "team": [
    {"role": "ORG", "name": "Пальчиков Леонид",  "fte": 1,   "from": "2026-01-01"},
    {"role": "BA",  "name": "Клейменова Анна",    "fte": 1,   "from": "2026-08-12"},
    {"role": "FE",  "name": "Самойло Андрей",     "fte": 1,   "from": "2026-08-01",
     "username": "ASamoylo"}
  ]
}
```

- `role` ∈ ORG, ARC, DS, BA, FE, BE, QA, DVO.
- Ушедших (в таблице «был … до ДД.ММ») **не включать**.
- Если у роли по ходу проекта менялся FTE (пример был у Самойло 0.2→1.0) —
  добавить `"fteFull": 1.0, "fromFull": "2026-08-01"`.
- Вакансии-гипотезы найма (FE-2, BE-1, QA-2) в этот файл **не вносить** —
  билдер добавит их сам с `from` не раньше 01.09.2026.

---

## 3. Что билдер НЕ трогает в режиме `gantt`

Мёрж со старым `data.json` сохраняет как есть: `usm`, `risks`, `questions`,
`assumptions`, `glossary`, `stakeholders`, `dependencies`, `acceptance`,
`sprints`, `okr*`, `scope_dec`, `mvp`, `weekly`, `blockersNow`. Их обновляют
режимы `registries` и `usm` (следующие шаги переработки).
