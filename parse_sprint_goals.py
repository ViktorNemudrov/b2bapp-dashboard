"""Цели спринтов (Confluence 1562746234 «Реализация») → sprint_goals.json.

Виктор фиксирует цели каждого спринта на странице «Реализация»: блок-expand
«Спринт N (дд.мм.гг-дд.мм.гг)», внутри нумерованный список целей; после
закрытия спринта к цели дописывается итог через « - »/« — » («выполнено»,
«частично…», «не выполнено…», «сняли…»). Страница «Статус для руководства»
показывает итоги закрытого спринта и цели текущего (26.10.2026).

Вход — та же браузерная выгрузка, что и для «Плана ручного» (ключ realizacia):
    python parse_sprint_goals.py cf/cf_plan_manual_2610.json sprint_goals.json
"""
import html
import json
import re
import sys

# Блоки спринтов бывают в одной ячейке разметки (С3 и С4 — 26.10.2026),
# поэтому тело блока — до начала следующего блока, а не до конца ячейки.
EXPAND_RE = re.compile(r'<ac:structured-macro[^>]*ac:name="expand"[^>]*>\s*<ac:parameter[^>]*>(Спринт\s*(\d+)[^<]*)</ac:parameter>', re.S)
LI_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.S)
# Итог — после ПОСЛЕДНЕГО « - »/« — », за которым слово-итог (жадный префикс).
RESULT_RE = re.compile(r"^(.*)\s[-—–]\s+((?:не\s+)?(?:выполнен\w*|достигнут\w*|частично|снял\w*|решено|решён|перенес\w*).*)$", re.I | re.S)


def text(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def status_of(res):
    r = (res or "").lower()
    if not r:
        return "open"
    if r.startswith("не "):
        return "fail"
    if r.startswith("частично"):
        return "partial"
    if r.startswith(("снял", "перенес")):
        return "dropped"
    return "done"


def main(src, dst):
    raw = json.load(open(src, encoding="utf-8"))
    page = raw["realizacia"]
    st = page["storage"]
    sprints = []
    ms = list(EXPAND_RE.finditer(st))
    for i, m in enumerate(ms):
        title, n = text(m.group(1)), int(m.group(2))
        body = st[m.end():ms[i + 1].start() if i + 1 < len(ms) else len(st)]
        body = body.split("Задачи в Jira")[0]
        goals = []
        for li in LI_RE.findall(body):
            t = text(li)
            rm = RESULT_RE.search(t)
            goal, res = (rm.group(1).strip(), rm.group(2).strip()) if rm else (t, "")
            goals.append({"text": goal, "result": res, "status": status_of(res)})
        intro = text(body.split("<ol")[0]) if "<ol" in body else text(body)
        sprints.append({"n": n, "title": title, "intro": intro[:300], "goals": goals})
    out = {"source": {"pageId": page["id"], "title": page["title"], "version": page["version"], "when": page["when"]},
           "sprints": sorted(sprints, key=lambda s: s["n"])}
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK {dst}: спринтов {len(sprints)}, целей {sum(len(s['goals']) for s in sprints)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "sprint_goals.json")
