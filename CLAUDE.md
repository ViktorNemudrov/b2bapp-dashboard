# B2BAPP Dashboard — инструкции для Claude Code

## Главное правило
После КАЖДОГО изменения любого файла в папке public/ — автоматически запускай python update.py для публикации на Vercel.

## Структура проекта
- public/index.html — главная страница дашборда
- public/pages/ — страницы разделов
- public/data/data.json — данные из Jira (обновляются отдельно)
- update.py — скрипт публикации в GitHub → Vercel

## Как вносить изменения
1. Внеси изменения в файл(ы)
2. Сразу запусти: python update.py
3. Дождись "Done! Vercel deploys automatically."
4. Сообщи что запушено

## Токен
Хранится в .env файле (GITHUB_TOKEN). Никогда не показывать в чате.
