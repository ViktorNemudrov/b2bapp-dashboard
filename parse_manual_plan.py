"""«План ручной» (Confluence 2666206915) → manual_plan.json.

Таблица аналитиков: строка = сценарий, колонки «Спринт N (дд.мм.гг-дд.мм.гг)»,
в ячейке — роли, работающие над сценарием в этом спринте («Аналитика»,
«Дизайн», «Бек 1»/«Бэк 2», «Фронт», «QA», через «+», «,» или перенос строки).
Бек 1 = Попов, Бек 2 = Григоркин (Виктор 26.10.2026); «Бек» без номера —
бэк без указания исполнителя.

Вход — выгрузка страницы из браузера (cf/cf_plan_manual_ДДММ.json: storage +
разобранная сетка grid[][] {t,cs,hl}). Запуск:
    python parse_manual_plan.py cf/cf_plan_manual_2610.json manual_plan.json
"""
import json
import re
import sys
from datetime import datetime

STAGE_TOKENS = (  # порядок важен: «Бек 1» раньше «Бек»
    (re.compile(r"аналитик", re.I), "AN"),
    (re.compile(r"дизайн", re.I), "DS"),
    (re.compile(r"б[еэ]к\s*1", re.I), "BE1"),
    (re.compile(r"б[еэ]к\s*2", re.I), "BE2"),
    (re.compile(r"б[еэ]к(?!\s*[12])", re.I), "BE"),
    (re.compile(r"фронт", re.I), "FE"),
    (re.compile(r"\bQA\b", re.I), "QA"),
)
SPRINT_HDR_RE = re.compile(r"Спринт\s*(\d+)\s*\((\d\d)\.(\d\d)\.(\d\d)\s*-\s*(\d\d)\.(\d\d)\.(\d\d)")
STAGE_ORDER = ["AN", "DS", "BE", "BE1", "BE2", "FE", "QA"]


def cell_stages(text):
    found = []
    for rx, sid in STAGE_TOKENS:
        if rx.search(text or ""):
            found.append(sid)
    return [s for s in STAGE_ORDER if s in found]


def main(src, dst):
    raw = json.load(open(src, encoding="utf-8"))
    grid = [[c["t"] for c in row] for row in raw["grid"]]
    head = grid[0]
    sprint_cols = {}
    sprints = []
    for ci, h in enumerate(head):
        m = SPRINT_HDR_RE.search(h)
        if m:
            n = int(m.group(1))
            d1 = datetime.strptime(f"{m.group(2)}.{m.group(3)}.20{m.group(4)}", "%d.%m.%Y").date()
            d2 = datetime.strptime(f"{m.group(5)}.{m.group(6)}.20{m.group(7)}", "%d.%m.%Y").date()
            sprint_cols[ci] = n
            sprints.append({"n": n, "start": d1.isoformat(), "end": d2.isoformat()})
    rows = []
    for r in grid[1:]:
        if len(r) < 6 or not r[1].strip():
            continue
        cells = {}
        for ci, n in sprint_cols.items():
            st = cell_stages(r[ci] if ci < len(r) else "")
            if st:
                cells[str(n)] = st
        rows.append({
            "contour": r[0].strip(), "code": r[1].strip(), "name": r[2].strip(),
            "priority": r[3].strip().replace("Р", "P"),   # кириллическая «Р» в P3
            "owner": r[5].strip(), "cells": cells,
        })
    plan = raw.get("plan") or {}
    out = {
        "source": {"pageId": plan.get("id"), "title": plan.get("title"),
                   "version": plan.get("version"), "when": plan.get("when")},
        "beResources": {"BE1": "Попов", "BE2": "Григоркин"},
        "sprints": sprints,
        "rows": rows,
    }
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK {dst}: {len(rows)} сценариев, спринтов {len(sprints)}, "
          f"ячеек {sum(len(r['cells']) for r in rows)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "manual_plan.json")
