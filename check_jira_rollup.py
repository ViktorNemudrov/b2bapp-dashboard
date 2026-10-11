# -*- coding: utf-8 -*-
"""Проверка согласованности стори и эпиков с их задачами в Jira — ПЕРЕД сборкой дашборда.

Правило Виктора 11.10.2026:
- если хоть одна задача стори в любом статусе, кроме «Бэклог», — стори не может
  быть в «Бэклог» (должна быть «Разработка»), а её «Дата начала» (customfield_18100)
  = самая ранняя «Дата начала» среди таких задач;
- аналогично эпик: если в нём есть стори/задачи в работе — эпик не в «Бэклог»
  («В работе»), «Дата начала» эпика = самая ранняя дата начала его стори
  (и задач эпика без стори).

Результат — список правок (rollup_fixes.json + печать). Сами правки делаются в
Jira до сбора дашборда, после чего выгрузку повторяют. Нужен дамп с полями
status, customfield_18100, customfield_10901, issuelinks (см. SKILL.md §1.1).

python check_jira_rollup.py [--jira jira_dump.json] [--out rollup_fixes.json]
"""
import argparse
import json
import sys

BACKLOG = "Бэклог"
DONE = {"Завершена", "Waiting for release", "Отклонена"}
STORY_TARGET = "Разработка"
EPIC_TARGET = "В работе"
START = "customfield_18100"
TYPES = {"3": "task", "20600": "task", "10600": "story", "10500": "epic"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jira", default="jira_dump.json")
    ap.add_argument("--out", default="rollup_fixes.json")
    a = ap.parse_args()
    raw = json.load(open(a.jira, encoding="utf-8"))
    issues = raw["issues"] if isinstance(raw, dict) else raw
    by_type = {"task": [], "story": [], "epic": []}
    for i in issues:
        t = TYPES.get(str(i["fields"]["issuetype"]["id"]))
        if t:
            by_type[t].append(i)
    if not any(START in i["fields"] for i in issues):
        sys.exit(f"В дампе нет поля {START} («Дата начала») — добавьте его в fields выгрузки")
    story_keys = {s["key"] for s in by_type["story"]}

    def parent_of(t):
        parts = [l["inwardIssue"]["key"] for l in (t["fields"].get("issuelinks") or [])
                 if (l.get("type") or {}).get("name") == "Part" and l.get("inwardIssue")]
        return next((k for k in parts if k in story_keys), None)

    tasks = [{"key": t["key"], "status": t["fields"]["status"]["name"], "start": t["fields"].get(START),
              "parent": parent_of(t), "epic": t["fields"].get("customfield_10901")} for t in by_type["task"]]
    fixes, warn = [], []

    def need(key, kind, status, start, exp_status, exp_start, why):
        ch = {}
        if exp_status and status == BACKLOG:
            ch["status"] = [status, exp_status]
        if exp_start and start != exp_start:
            ch["start"] = [start, exp_start]
        if ch:
            fixes.append({"key": key, "type": kind, "changes": ch, "why": why})

    story_start = {}
    for s in by_type["story"]:
        f = s["fields"]
        kids = [t for t in tasks if t["parent"] == s["key"]]
        act = [t for t in kids if t["status"] != BACKLOG]
        no_date = [t["key"] for t in act if not t["start"]]
        if no_date:
            warn.append(f"{s['key']}: у задач не в «Бэклог» нет «Даты начала»: {', '.join(no_date)}")
        exp = min((t["start"] for t in act if t["start"]), default=None)
        story_start[s["key"]] = (exp, bool(act))
        if act:
            first = min((t for t in act if t["start"]), key=lambda t: t["start"], default=act[0])
            need(s["key"], "story", f["status"]["name"], f.get(START), STORY_TARGET, exp,
                 f"задач не в «Бэклог»: {len(act)} из {len(kids)}; самая ранняя — {first['key']} ({first['status']}, с {first['start']})")
        elif f["status"]["name"] not in (BACKLOG,) and f["status"]["name"] not in DONE:
            warn.append(f"{s['key']}: стори в «{f['status']['name']}», но {'задач нет' if not kids else 'все задачи в «Бэклог»'} — проверить")

    for e in by_type["epic"]:
        f = e["fields"]
        sts = [s for s in by_type["story"] if s["fields"].get("customfield_10901") == e["key"]]
        orph = [t for t in tasks if t["epic"] == e["key"] and not t["parent"] and t["status"] != BACKLOG]
        starts = [story_start[s["key"]][0] for s in sts if story_start[s["key"]][0]] + [t["start"] for t in orph if t["start"]]
        active = any(story_start[s["key"]][1] for s in sts) or bool(orph)
        if active:
            need(e["key"], "epic", f["status"]["name"], f.get(START), EPIC_TARGET, min(starts, default=None),
                 f"стори в работе: {sum(story_start[s['key']][1] for s in sts)} из {len(sts)}")

    json.dump({"fixes": fixes, "warnings": warn}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Правок: {len(fixes)} (статус: {sum('status' in x['changes'] for x in fixes)}, дата начала: {sum('start' in x['changes'] for x in fixes)}); предупреждений: {len(warn)}")
    for x in fixes:
        c = x["changes"]
        parts = []
        if "status" in c:
            parts.append(f"статус {c['status'][0]} → {c['status'][1]}")
        if "start" in c:
            parts.append(f"дата начала {c['start'][0] or '—'} → {c['start'][1]}")
        print(f"  {x['type']:5} {x['key']}: {'; '.join(parts)}  ({x['why']})")
    for w in warn:
        print("  ! " + w)
    return 1 if fixes else 0


if __name__ == "__main__":
    sys.exit(main())
