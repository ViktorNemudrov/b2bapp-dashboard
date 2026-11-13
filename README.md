# B2BAPP Dashboard

Дашборд проекта мобильного приложения «Билайн Бизнес» для микробизнеса: https://b2bapp-dashboard.vercel.app (статический сайт, деплой Vercel из `main`, клиентский пароль-гейт).

## Структура

```
public/
  index.html            — главная: прогноз, метрики, готовность эпиков, матрица рисков, рост скоупа
  shared-nav.js         — меню, пароль-гейт, палитра статусов, автоссылки Jira/Confluence, облачко задач этапа
  shared.css            — общие стили (index.html их не подключает)
  data/
    data.json           — все данные сайта (собирает build_dashboard.py)
    baselines.json      — слепки плана для сравнения на ганте
    audit.json          — аудит задач по аналитикам (собирает build_audit.py)
    changelog.json      — история версий дашборда (ведётся вручную)
  pages/
    status.html         — «Статус для руководства» (7 вкладок, блок трека ВП, «Что изменилось»)
    gantt.html          — диаграмма Ганта (виды: эпики / сценарии / этапы по сценариям) + gantt-compare.js
    resources.html      — команда и загрузка по спринтам/месяцам
    vacations.html      — график отпусков
    audit.html          — аудит задач по аналитикам (правки оформления Jira + отстающие этапы P4)
    changelog.html      — «Что нового»: история версий дашборда (рисует data/changelog.json; запись сверху при каждом выпуске)
    risks.html, assumptions.html — реестры из Confluence
```

## Сборка

| Скрипт | Что делает |
|---|---|
| `fetch_jira_dumps.js` | выгрузка из Jira (в консоли залогиненной вкладки btask) → `jira_full_dump.json` и `jira_dump.json` |
| `build_dashboard.py` | Jira-дамп + команда + «План ручной» + цели спринтов + реестр сценариев + отпуска → `data.json`, `baselines.json` |
| `build_audit.py` | полная выгрузка Jira + реестр MVP v.2 + `data.json` → `audit.json` |
| `import_registers.py` | реестры рисков и допущений из Confluence → `data.json` |
| `parse_manual_plan.py`, `parse_sprint_goals.py` | разбор страниц Confluence → `manual_plan.json`, `sprint_goals.json` |
| `check_jira_rollup.py` | проверка статусов и дат стори/эпиков против задач |
| `build_rag_master.py` (+ `rag_compare.js`) | `rag/MASTER_11_план_работ.md` для RAG |

Полный порядок обновления (выгрузки из Jira/Confluence через браузер, сборка, проверки, публикация) — скилл Claude Code `b2bapp-dashboard-update`; копия: `Desktop\B2BAPP\13_Скиллы_и_инструкции_Claude\Скиллы_и_память_Claude_актуальные\Claude_Code_скиллы\`. Формат Jira-дампа — `DUMP_FORMAT.md`.

Транзитные входные файлы (`jira_dump.json`, `jira_full_dump.json`, `team_dump.json`, `vacations.json`) в git не попадают.
