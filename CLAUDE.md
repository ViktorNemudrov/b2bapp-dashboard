# B2BAPP Dashboard — инструкции для ИИ

Актуальная процедура обновления и все договорённости с Виктором — скилл `b2bapp-dashboard-update`
(у Claude Code — `~\.claude\skills\b2bapp-dashboard-update\SKILL.md`; копия для других ИИ —
`Desktop\B2BAPP\13_Скиллы_и_инструкции_Claude\Скиллы_и_память_Claude_актуальные\`). Структура репо — `README.md`.

## Главные правила
- Данные сайта считают скрипты (`build_dashboard.py`, `build_audit.py`); страницы в `public/` только рисуют JSON.
- База `data.json` для сборки — `origin/main` (`git fetch` перед работой). Билдер мёржит: ключи, которые он
  не считает (реестры, `vpTrack`, `teamConfluence`…), переносит из старого файла; мёртвые ключи — `DEAD_KEYS`.
- `--data` и `--out` — в одной папке (`public/data/`): иначе пропадут задачи прошлых слепков в `baselines.json`.
- Битый JSON роняет все страницы — парс-чек перед пушем. Смотреть сайт до пуша: `python -m http.server`
  из `public/` → `http://127.0.0.1:…` (на localhost пароль-гейт пропускает; пароль на проде не вводить).
- Деплой — только `git commit` + `git push origin main` (Vercel собирает сам). `update.py` — устаревший запасной путь.
- Файлы в git добавлять поимённо; `cf/`, `rag/`, `jira_fix_plan/` и дампы — рабочие, не коммитить.
- Часть файлов в CRLF (`status.html`, `gantt.html`, `build_dashboard.py`…) — сохранять окончания строк.
