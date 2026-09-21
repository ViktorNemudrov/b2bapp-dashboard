#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dashboard.py — детерминированная сборка public/data/data.json для B2BAPP-дашборда.

ЗАЧЕМ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ
--------------------------
Раньше data.json собирался "в голове" Claude на каждом прогоне — отсюда провалы
09.07/10.07/21.07 (плоский ganttV2, задачи-сироты, нулевые оценки, плейсхолдеры
в данных). Теперь вся АРИФМЕТИКА живёт здесь, в коде, с самопроверками-ассертами.
Забыть шаг или "придумать правдоподобное" невозможно — скрипт либо считает из
реального сырья, либо падает на ассерте.

РАЗДЕЛЕНИЕ ТРУДА (не менять без согласования с Виктором):
  • Claude (в сессии, браузер) — собирает СЫРЬЁ: jira_dump.json, team_dump.json.
  • Этот скрипт (гоняет Claude Code локально) — считает data.json.
  • Фронт дашборда — только РИСУЕТ. Ничего не досчитывает.

  Если правка про ЛОГИКУ расчёта (как считается гант/критпуть/загрузка/скоуп) —
  это ЗДЕСЬ, и правит Claude в сессии (он автор скрипта). Claude Code такие
  просьбы не выполняет сам — см. CLAUDE.md, раздел "Маршрутизация".
  Если правка про ВИЗУАЛ — это фронт, правит Claude Code.

РЕЖИМЫ
------
  gantt      — часто. Пересобирает: ganttV2, summary, kpi, metrics, roleEstimates,
               storyStatuses, taskStatuses, mvpScope, resourcePlan, epicProgress,
               scopeGrowth, baselines, milestones(статусы), ganttAssumptions,
               criticalPathExplained, team, totalIssues, refreshedAt/generatedAt.
               НЕ трогает: usm, risks, questions, assumptions, glossary,
               stakeholders, dependencies, acceptance, blockersNow, weekly,
               okr* — они мёржатся из старого data.json без изменений.
  registries — (todo, отдельный шаг) реестры из confluence_dump.json.
  usm        — (todo, отдельный шаг) полный проход Confluence+Jira.

ЗАПУСК (Claude Code, локально, из корня репо):
  python build_dashboard.py --mode gantt \
      --jira  jira_dump.json \
      --team  team_dump.json \
      --data  public/data/data.json \
      --out   public/data/data.json      # можно тот же файл (мёрж) или новый для сверки

Сырьё (jira_dump.json / team_dump.json) — формат в файлах *_FORMAT.md рядом.
"""

import argparse
import json
import re
import sys
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta

MSK = "+03:00"

# ─────────────────────────────────────────────────────────────────────────────
#  ПРОИЗВОДСТВЕННЫЙ КАЛЕНДАРЬ РФ — праздники/переносы.
#  ПРАВИТЬ ЗДЕСЬ (или вынести в holidays.json и читать — на усмотрение Claude Code).
#  Формат: строки 'YYYY-MM-DD'. Это НЕРАБОЧИЕ дни (вдобавок к сб/вс).
#  2026 — по утверждённому производственному календарю РФ.
#  2027–2028 — предварительно (новогодние + основные), уточнить при появлении.
# ─────────────────────────────────────────────────────────────────────────────
HOLIDAYS = {
    # 2026
    "2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
    "2026-01-08", "2026-02-23", "2026-03-09", "2026-05-01", "2026-05-11",
    "2026-06-12", "2026-11-04",
    # 2027 (предварительно)
    "2027-01-01", "2027-01-04", "2027-01-05", "2027-01-06", "2027-01-07",
    "2027-01-08", "2027-02-23", "2027-03-08", "2027-05-03", "2027-05-10",
    "2027-06-14", "2027-11-04",
    # 2028 (предварительно)
    "2028-01-03", "2028-01-04", "2028-01-05", "2028-01-06", "2028-01-07",
    "2028-02-23", "2028-03-08", "2028-05-01", "2028-05-09", "2028-06-12",
    "2028-11-06",
}
HOURS_PER_DAY = 8
VACANCY_HIRE_MIN = date(2026, 9, 1)   # вакансии-гипотезы найма не раньше этой даты
DEADLINE = date(2026, 12, 10)          # веха MVP

# Зависимости ролей ВНУТРИ стори (порядок фаз). Строго последовательная цепочка,
# без параллельных пар (правка Виктора 21.09.2026): ARC→BA→DS→BE→FE→QA.
# ORG и DVO — параллельно всему (не в цепочке).
ROLE_PHASE = {"ARC": 0, "BA": 1, "DS": 2, "BE": 3, "FE": 4, "QA": 5}
PARALLEL_ROLES = {"ORG", "DVO", "OTHER"}  # не встраиваются в фазовую цепочку

# ─────────────────────────────────────────────────────────────────────────────
#  Календарные помощники
# ─────────────────────────────────────────────────────────────────────────────
def is_workday(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS

def next_workday(d: date) -> date:
    while not is_workday(d):
        d += timedelta(days=1)
    return d

def add_work_hours(start: date, hours: float, fte: float) -> date:
    """Вернуть дату окончания: сколько РАБОЧИХ дней займут hours при данном fte."""
    if hours <= 0:
        return next_workday(start)
    cap = max(HOURS_PER_DAY * fte, 0.1)
    days_needed = max(1, -(-int(round(hours)) // int(round(cap))))  # ceil
    d = next_workday(start)
    used = 1
    while used < days_needed:
        d = next_workday(d + timedelta(days=1))
        used += 1
    return d

def workdays_between(a: date, b: date):
    """Итератор рабочих дней [a..b] включительно."""
    d = next_workday(a)
    while d <= b:
        yield d
        d = next_workday(d + timedelta(days=1))

def month_normhours(year: int, month: int) -> int:
    """Норма рабочих часов месяца по производственному календарю РФ."""
    d = date(year, month, 1)
    cnt = 0
    while d.month == month:
        if is_workday(d):
            cnt += 1
        d += timedelta(days=1)
    return cnt * HOURS_PER_DAY

def parse_dt(s):
    if not s:
        return None
    s = s.replace("Z", "+0000")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s[:19]).date()
    except Exception:
        return None

# ─────────────────────────────────────────────────────────────────────────────
#  Парсинг сырья Jira
# ─────────────────────────────────────────────────────────────────────────────
ISSUETYPE = {"3": "task", "20600": "task", "10600": "story", "10500": "epic"}
ROLE_RE = re.compile(r"^\s*(?:\d+[.:]\s*)?\[([A-Za-zА-Яа-я]+)\]")
PRIO_RE = re.compile(r"^\s*(\d+)[.:]")

def role_from_summary(summary: str) -> str:
    m = ROLE_RE.match(summary or "")
    if not m:
        return "OTHER"
    r = m.group(1).upper()
    known = {"BA", "BE", "FE", "DS", "ARC", "ORG", "DVO", "QA"}
    return r if r in known else "OTHER"

def prio_from_summary(summary: str):
    m = PRIO_RE.match(summary or "")
    return int(m.group(1)) if m else 9999

def status_category(status_name: str) -> str:
    s = (status_name or "").lower()
    if s in ("завершена", "готово", "done", "closed", "resolved"):
        return "done"
    if s in ("в работе", "разработка", "review", "анализ", "in progress"):
        return "in_progress"
    return "backlog"

def is_vacant(summary: str) -> bool:
    s = (summary or "").lower()
    return s.strip() == "вакантная" or "вакантн" in s

def seconds_to_h(x):
    return round((x or 0) / 3600) if x else 0

def normalize_issue(raw):
    """Один сырой issue Jira → плоский dict. Всё, что нужно билдеру."""
    f = raw.get("fields", {})
    itype_id = str((f.get("issuetype") or {}).get("id", ""))
    itype = ISSUETYPE.get(itype_id, "other")  # Initiative и пр. → other, в гант не идут
    summary = f.get("summary", "") or ""
    tt = f.get("timetracking") or {}
    est = tt.get("originalEstimateSeconds") or 0
    spent = tt.get("timeSpentSeconds") or f.get("timespent") or 0
    assignee = f.get("assignee") or {}
    labels = f.get("labels") or []
    # Part-связи и явные Blocks
    part_parent = None      # для задачи: ключ её истории
    blocks_deps = []        # ключи, которые блокируют этот issue
    for lk in (f.get("issuelinks") or []):
        t = (lk.get("type") or {})
        name = t.get("name", "")
        if name == "Part" and lk.get("inwardIssue"):
            # ВАЖНО (проверено на реальных данных 22.08.2026):
            # у ЗАДАЧИ Part-связь хранит родителя-стори в inwardIssue
            # (type.inward = "is part of"); outwardIssue у задачи отсутствует.
            # У стори — наоборот (outwardIssue = задача), но нам это не нужно:
            # родителя мы всегда резолвим от задачи вверх.
            part_parent = lk["inwardIssue"].get("key")
        if name in ("Blocks", "Dependency", "Blocked"):
            inw = lk.get("inwardIssue")
            if inw and t.get("inward", "").lower().startswith(("is blocked", "блок")):
                blocks_deps.append(inw.get("key"))
    return {
        "key": raw.get("key"),
        "type": itype,
        "summary": summary,
        "status": (f.get("status") or {}).get("name", ""),
        "assignee": assignee.get("name") or assignee.get("key") or "",
        "created": parse_dt(f.get("created")),
        "resolutiondate": parse_dt(f.get("resolutiondate")),
        "duedate": parse_dt(f.get("duedate")),
        "updated": parse_dt(f.get("updated")),
        "labels": labels,
        "estimateH": seconds_to_h(est),
        "spentH": seconds_to_h(spent),
        "epicLink": f.get("customfield_10901"),      # story → epic
        "epicName": f.get("customfield_10903"),       # у эпика — имя
        "partParent": part_parent,                     # task → story
        "blocksDeps": blocks_deps,
        "role": role_from_summary(summary) if itype == "task" else None,
        "priority": prio_from_summary(summary),
        "epicPriorityRaw": f.get("epicPriority"),  # явное поле эпика, если прислано выгрузкой
        "vacant": is_vacant(summary),
    }

def load_jira(path):
    raw = json.load(open(path, encoding="utf-8"))
    issues = raw.get("issues", raw) if isinstance(raw, dict) else raw
    out = [normalize_issue(r) for r in issues]
    total = raw.get("total") if isinstance(raw, dict) else len(out)
    return out, (total or len(out))

# ─────────────────────────────────────────────────────────────────────────────
#  Ресурсы: team_dump (Confluence «Команда») + сверка Jira assignee + вакансии
# ─────────────────────────────────────────────────────────────────────────────
def build_resources(team, issues):
    """
    team: список {role,name,fte,from,fteFull?,fromFull?,username?} из Confluence.
    Добавляем вакансии-гипотезы найма там, где по эпикам роль нужна, а живого нет.
    id ресурса: ROLE-N (по порядку в роли, реальные раньше вакансий).
    """
    by_role = defaultdict(list)
    for t in team:
        by_role[t["role"]].append(t)

    # username из Jira assignee — по совпадению фамилии (для подсветки «моих» задач)
    assignees = {i["assignee"] for i in issues if i["assignee"]}
    def guess_username(name):
        fam = (name or "").split()[0].lower()
        for a in assignees:
            if fam and fam[:4] in a.lower():
                return a
        return None

    resources = []
    counters = Counter()
    for role in ["ORG", "ARC", "DS", "BA", "FE", "BE", "QA", "DVO"]:
        for t in sorted(by_role.get(role, []), key=lambda x: x.get("from", "")):
            counters[role] += 1
            rid = f"{role}-{counters[role]}"
            res = {
                "id": rid, "role": role, "name": t["name"],
                "fte": t.get("fte", 1), "from": t.get("from"),
                "vacant": False,
            }
            if t.get("fteFull"):
                res["fteFull"] = t["fteFull"]; res["fromFull"] = t.get("fromFull")
            un = t.get("username") or guess_username(t["name"])
            if un:
                res["username"] = un
            resources.append(res)

    # Вакансии-гипотезы: минимальный костяк ролей, если реального нет.
    # Правило (Виктор): from не раньше 01.09.2026. Список ролей-гипотез — как в
    # текущем data.json: FE-2, BE-1, QA-2 (второй фронт, бэк, второй QA).
    need_vacancies = [("FE", 2), ("BE", 1), ("QA", 2)]
    have = {r["id"] for r in resources}
    for role, want_idx in need_vacancies:
        rid = f"{role}-{want_idx}"
        if rid in have:
            continue
        counters[role] = max(counters[role], want_idx)
        resources.append({
            "id": rid, "role": role, "name": f"Вакантно {rid}",
            "fte": 1, "from": VACANCY_HIRE_MIN.isoformat(), "vacant": True,
        })
    return resources

# ─────────────────────────────────────────────────────────────────────────────
#  Планировщик ганта (per-task, MVP-only)
# ─────────────────────────────────────────────────────────────────────────────
def resolve_epic_priority(e):
    """epicPriority из выгрузки приоритетнее текстового префикса эпика
    (у него бывают устаревшие каталожные номера, см. кейс "5. Онбординг")."""
    if not e:
        return 9999
    return e["epicPriorityRaw"] if e.get("epicPriorityRaw") is not None else e["priority"]

def plan_gantt(issues, resources):
    """
    Возвращает items[] (epic+story+task) с датами, ресурсами, критпутём.
    Планируем ТОЛЬКО MVP (метка mvp у стори) + их задачи. Вакантные исключены.
    Завершённые — факт. В работе — факт-старт + остаток. Бэклог — жадное
    назначение по очередям ресурсов без простоя, приоритет = префикс стори.
    """
    issues = [i for i in issues if not i["vacant"]]
    by_key = {i["key"]: i for i in issues}

    epics = {i["key"]: i for i in issues if i["type"] == "epic"}
    stories = {i["key"]: i for i in issues if i["type"] == "story"}
    tasks = [i for i in issues if i["type"] == "task"]

    # MVP-фильтр: стори с меткой mvp; их задачи — по Part-связи.
    mvp_story_keys = {k for k, s in stories.items() if "mvp" in [l.lower() for l in s["labels"]]}
    mvp_tasks = [t for t in tasks if t["partParent"] in mvp_story_keys]

    # Очереди ресурсов: следующая свободная дата по каждому ресурсу.
    res_free = {r["id"]: parse_dt(r["from"]) or date(2026, 1, 1) for r in resources}
    res_by_role = defaultdict(list)
    for r in resources:
        res_by_role[r["role"]].append(r)

    def pick_resource(role, earliest):
        """Ресурс нужной роли, который освободится раньше всех (но не раньше выхода)."""
        pool = res_by_role.get(role) or res_by_role.get("OTHER") or resources
        best = min(pool, key=lambda r: max(res_free[r["id"]], parse_dt(r["from"]) or earliest, earliest))
        return best

    planned = {}   # key → {start,end,resource,...}

    # Сортировка задач: по приоритету ЭПИКА (числовой префикс в summary самого
    # эпика, а не дата создания и не префикс стори), затем приоритет стори
    # внутри эпика, затем фаза роли, затем ключ. Правка Виктора 21.09.2026 —
    # раньше сортировка шла только по префиксу стори, который локальный на
    # каждый эпик (снова начинается с "1." в каждом эпике), из-за чего порядок
    # эпиков получался произвольным (фактически — по порядку в jira_dump.json).
    def story_prio(t):
        s = stories.get(t["partParent"])
        if not s:
            return (9999, 9999)
        return (resolve_epic_priority(epics.get(s.get("epicLink"))), s["priority"])
    ordered = sorted(mvp_tasks, key=lambda t: (story_prio(t),
                                               ROLE_PHASE.get(t["role"], 1),
                                               t["priority"], t["key"]))

    # Хранит окончание последней фазы внутри стори (для зависимости фаз).
    story_phase_end = defaultdict(lambda: defaultdict(lambda: None))  # story→phase→date

    for t in ordered:
        role = t["role"]
        cat = status_category(t["status"])
        st_key = t["partParent"]

        if cat == "done":
            start = t["created"] or date(2026, 1, 1)
            end = t["resolutiondate"] or t["updated"] or start
            res = pick_resource(role, start)
        else:
            # Зависимость фаз внутри стори: не раньше конца предыдущей фазы.
            phase = ROLE_PHASE.get(role, None)
            dep_end = None
            if phase is not None and phase > 0:
                for ph in range(phase):
                    e = story_phase_end[st_key][ph]
                    if e and (dep_end is None or e > dep_end):
                        dep_end = e
            # Явные Blocks
            for dk in t["blocksDeps"]:
                if dk in planned and (dep_end is None or planned[dk]["end"] > dep_end):
                    dep_end = planned[dk]["end"]

            res = pick_resource(role, dep_end or date(2026, 1, 1))
            fte = res["fte"]
            earliest = max(res_free[res["id"]],
                           parse_dt(res["from"]) or date(2026, 1, 1),
                           dep_end or date(2026, 1, 1))
            remaining = t["estimateH"] - t["spentH"] if cat == "in_progress" else t["estimateH"]
            remaining = max(remaining, 0)
            start = next_workday(earliest)
            end = add_work_hours(start, remaining, fte)
            res_free[res["id"]] = next_workday(end + timedelta(days=1))
            if phase is not None:
                prev = story_phase_end[st_key][phase]
                if prev is None or end > prev:
                    story_phase_end[st_key][phase] = end

        planned[t["key"]] = {
            "start": start, "end": end, "resource": res["id"], "category": cat,
        }

    # ── Сборка items[] ────────────────────────────────────────────────────────
    items = []
    # задачи
    for t in mvp_tasks:
        p = planned.get(t["key"])
        if not p:
            continue
        items.append({
            "key": t["key"], "type": "task", "parent": t["partParent"],
            "epic": (stories.get(t["partParent"]) or {}).get("epicLink"),
            "summary": t["summary"], "role": t["role"], "priority": t["priority"],
            "estimateH": t["estimateH"], "spentH": t["spentH"],
            "status": t["status"], "category": p["category"],
            "start": p["start"].isoformat(), "end": p["end"].isoformat(),
            "resource": p["resource"], "onCriticalPath": False,
            "deps": t["blocksDeps"],
        })
    # стори (агрегат из их задач)
    for sk in mvp_story_keys:
        s = stories[sk]
        kids = [it for it in items if it["parent"] == sk]
        if kids:
            start = min(it["start"] for it in kids)
            end = max(it["end"] for it in kids)
        else:
            start = (s["created"] or date(2026, 1, 1)).isoformat()
            end = start
        cat = "done" if kids and all(it["category"] == "done" for it in kids) \
              else ("in_progress" if any(it["category"] != "backlog" for it in kids) else "backlog")
        items.append({
            "key": sk, "type": "story", "parent": s["epicLink"], "epic": s["epicLink"],
            "summary": s["summary"], "priority": s["priority"],
            "estimateH": sum(it["estimateH"] for it in kids),
            "spentH": sum(it["spentH"] for it in kids),
            "start": start, "end": end, "category": cat,
            "onCriticalPath": False, "deps": [],
        })
    # эпики (агрегат из их стори)
    epic_keys = {s["epicLink"] for s in [stories[k] for k in mvp_story_keys] if s.get("epicLink")}
    for ek in epic_keys:
        e = epics.get(ek)
        kids = [it for it in items if it["type"] == "story" and it["epic"] == ek]
        if not kids:
            continue
        start = min(it["start"] for it in kids)
        end = max(it["end"] for it in kids)
        cat = "done" if all(it["category"] == "done" for it in kids) \
              else ("in_progress" if any(it["category"] != "backlog" for it in kids) else "backlog")
        items.append({
            "key": ek, "type": "epic", "parent": None, "epic": ek,
            "summary": (e or {}).get("summary", ek),
            "priority": resolve_epic_priority(e),
            "estimateH": sum(it["estimateH"] for it in kids),
            "spentH": sum(it["spentH"] for it in kids),
            "start": start, "end": end, "category": cat,
            "onCriticalPath": False,
            "storiesTotal": len(kids),
            "storiesDone": sum(1 for it in kids if it["category"] == "done"),
            "deps": [],
        })

    # ── Критический путь: цепочка задач до max(end) ────────────────────────────
    # end_date держим как date (не ISO-строку!), иначе сравнение с DEADLINE и
    # .isoformat() падают. Баг найден Claude Code 22.08.2026, синхронизирован сюда.
    task_ends = [date.fromisoformat(it["end"]) for it in items if it["type"] == "task"]
    end_date = max(task_ends) if task_ends else None
    crit_res = None
    if end_date:
        end_iso = end_date.isoformat()
        tail = [it for it in items if it["type"] == "task" and it["end"] == end_iso]
        if tail:
            crit_res = tail[0]["resource"]
        # пометить критпуть: задачи ресурса-хвоста + их стори/эпики
        crit_tasks = {it["key"] for it in items
                      if it["type"] == "task" and it["resource"] == crit_res}
        crit_parents = {it["parent"] for it in items
                        if it["key"] in crit_tasks and it.get("parent")}
        crit_epics = {it["epic"] for it in items
                      if it["key"] in crit_parents and it.get("epic")}
        for it in items:
            if it["key"] in crit_tasks or it["key"] in crit_parents or it["key"] in crit_epics:
                it["onCriticalPath"] = True

    return items, end_date, crit_res, mvp_story_keys

# ─────────────────────────────────────────────────────────────────────────────
#  Производные секции из items[]
# ─────────────────────────────────────────────────────────────────────────────
def calc_resource_plan(items, resources):
    """resourcePlan[] в реальной форме дашборда: months[] с loadPct."""
    plan = []
    for r in resources:
        rid = r["id"]
        tasks = [it for it in items if it["type"] == "task" and it["resource"] == rid]
        if not tasks:
            continue
        month_hours = defaultdict(float)
        for it in tasks:
            a = date.fromisoformat(it["start"]); b = date.fromisoformat(it["end"])
            wdays = list(workdays_between(a, b))
            if not wdays:
                continue
            per = it["estimateH"] / len(wdays)
            for d in wdays:
                month_hours[f"{d.year:04d}-{d.month:02d}"] += per
        months = []
        for mkey in sorted(month_hours):
            y, m = int(mkey[:4]), int(mkey[5:7])
            fte = r["fte"]
            if r.get("fteFull") and r.get("fromFull") and mkey >= r["fromFull"][:7]:
                fte = r["fteFull"]
            norm = month_normhours(y, m)
            hp = round(month_hours[mkey])
            months.append({"month": mkey, "hoursPlanned": hp,
                           "normHours": norm,
                           "loadPct": round(hp / (norm * fte) * 100) if norm * fte else 0})
        plan.append({
            "resourceId": rid, "role": r["role"], "name": r["name"],
            "fte": r["fte"], "from": r["from"], "vacant": r.get("vacant", False),
            "taskCount": len(tasks),
            "hoursTotal": sum(it["estimateH"] for it in tasks),
            "months": months,
        })
    return plan

def calc_epic_progress(items):
    out = []
    for e in [it for it in items if it["type"] == "epic"]:
        out.append({
            "epicKey": e["key"], "epicName": e["summary"],
            "hoursTotal": e["estimateH"], "hoursSpent": e["spentH"],
            "storiesTotal": e.get("storiesTotal", 0),
            "storiesDone": e.get("storiesDone", 0),
            "start": e["start"], "end": e["end"],
        })
    return out

def calc_mvp_scope(items):
    inS, outS = [], []
    for s in [it for it in items if it["type"] == "story"]:
        rec = {"key": s["key"], "name": s["summary"], "readyDate": s["end"]}
        (inS if date.fromisoformat(s["end"]) <= DEADLINE else outS).append(rec)
    return {"inStories": inS, "outStories": outS,
            "rationale": "Отсечка 10.12.2026. Только MVP-стори."}

def calc_role_estimates(all_issues):
    """По ВСЕМ задачам проекта (не только MVP), без вакантных."""
    agg = defaultdict(lambda: {"count": 0, "estH": 0, "spentH": 0, "done": 0})
    for t in all_issues:
        if t["type"] != "task" or t["vacant"]:
            continue
        r = t["role"] or "OTHER"
        agg[r]["count"] += 1
        agg[r]["estH"] += t["estimateH"]
        agg[r]["spentH"] += t["spentH"]
        if status_category(t["status"]) == "done":
            agg[r]["done"] += 1
    return dict(agg)

def calc_status_counters(all_issues):
    story_st = Counter(); task_st = Counter()
    for i in all_issues:
        if i["vacant"]:
            continue
        if i["type"] == "story":
            story_st[i["status"]] += 1
        elif i["type"] == "task":
            task_st[i["status"]] += 1
    return dict(story_st), dict(task_st)

# ─────────────────────────────────────────────────────────────────────────────
#  Самопроверки (ассерты) — из §3.1/§3.2 скилла, теперь как КОД
# ─────────────────────────────────────────────────────────────────────────────
def self_checks(items, gv2, mvp_scope, resource_plan, epic_progress):
    errs = []
    types = Counter(it["type"] for it in items)
    if types["story"] == 0 or types["task"] == 0:
        errs.append("ganttV2.items: нет story или task — иерархия не построена")
    task_keys = [it["key"] for it in items if it["type"] == "task"]
    if len(task_keys) != len(set(task_keys)):
        errs.append("ganttV2.items: дубли ключей задач — сгенерировано по шаблону")
    epic_set = {it["key"] for it in items if it["type"] == "epic"}
    story_set = {it["key"] for it in items if it["type"] == "story"}
    orphan_stories = [it["key"] for it in items
                      if it["type"] == "story" and it["parent"] not in epic_set]
    if len(orphan_stories) == types["story"] and types["story"]:
        errs.append("ganttV2.items: 100% стори-сирот — parent не резолвится")
    orphan_tasks = [it["key"] for it in items
                    if it["type"] == "task" and it["parent"] not in story_set]
    if len(orphan_tasks) == types["task"] and types["task"]:
        errs.append("ganttV2.items: 100% задач-сирот — parent не резолвится")
    date_pairs = Counter((it["start"], it["end"]) for it in items if it["type"] == "task")
    if date_pairs and date_pairs.most_common(1)[0][1] > max(20, 0.6 * len(task_keys)):
        errs.append("ganttV2.items: даты массово одинаковы — не считались по задаче")
    if items and all(it["estimateH"] == 0 for it in items):
        errs.append("ganttV2.items: все estimateH = 0")
    placeholders = {"Эпик", "Роль (ресурс)", "Старт", "Финиш"}
    for it in items:
        if str(it.get("summary")) in placeholders or str(it.get("start")) in placeholders:
            errs.append(f"ganttV2.items: утечка плейсхолдера в {it['key']}")
            break
    if not isinstance(gv2, dict) or not isinstance(gv2.get("items"), list):
        errs.append("ganttV2 не объект с items[]")
    if not isinstance(mvp_scope, dict) or not isinstance(mvp_scope.get("inStories"), list):
        errs.append("mvpScope не объект с inStories[]")
    if not isinstance(resource_plan, list) or not isinstance(epic_progress, list):
        errs.append("resourcePlan/epicProgress должны быть массивами")
    for rp in resource_plan:
        if "months" not in rp:
            errs.append(f"resourcePlan[{rp.get('resourceId')}]: нет months[]"); break
        if not rp.get("name"):
            errs.append(f"resourcePlan[{rp.get('resourceId')}]: пустое name"); break
    return errs

# ─────────────────────────────────────────────────────────────────────────────
#  Главный проход режима gantt
# ─────────────────────────────────────────────────────────────────────────────
def run_gantt(args):
    now = datetime.now().astimezone()
    now_iso = now.replace(microsecond=0).isoformat()
    today = now.date()

    issues, total_issues = load_jira(args.jira)
    team = json.load(open(args.team, encoding="utf-8"))
    team = team.get("team", team) if isinstance(team, dict) else team
    old = json.load(open(args.data, encoding="utf-8"))

    resources = build_resources(team, issues)
    items, end_date, crit_res, mvp_story_keys = plan_gantt(issues, resources)

    mvp_scope = calc_mvp_scope(items)
    resource_plan = calc_resource_plan(items, resources)
    epic_progress = calc_epic_progress(items)

    # Единый проход счётчиков из items[] (MVP-подмножество)
    mvp_epics = [it for it in items if it["type"] == "epic"]
    mvp_stories = [it for it in items if it["type"] == "story"]
    mvp_tasks_it = [it for it in items if it["type"] == "task"]
    hours_total = sum(it["estimateH"] for it in mvp_epics)
    hours_spent = sum(it["spentH"] for it in mvp_epics)
    stories_done = sum(1 for it in mvp_stories if it["category"] == "done")
    tasks_done = sum(1 for it in mvp_tasks_it if it["category"] == "done")
    completion = round(hours_spent / hours_total * 100, 1) if hours_total else 0
    crit_end_iso = end_date.isoformat() if end_date else None
    days_to_deadline = (DEADLINE - today).days

    # Счётчики по ВСЕМ задачам проекта (не MVP)
    story_st, task_st = calc_status_counters(issues)
    role_est = calc_role_estimates(issues)

    ganttV2 = {
        "generatedAt": now_iso,
        "workCalendar": {"holidays": sorted(HOLIDAYS), "hoursPerDay": HOURS_PER_DAY},
        "resources": resources,
        "items": items,
        "mvpScope": mvp_scope,
        "criticalPathExplained": {
            "method": "Критический путь = цепочка задач до max(end) по ресурсу-хвосту.",
            "endDate": crit_end_iso,
            "resource": crit_res,
            "conclusion": ("Успеваем к 10.12.2026" if end_date and end_date <= DEADLINE
                           else f"НЕ успеваем: критпуть до {crit_end_iso}, дедлайн 10.12.2026"),
            "steps": [
                "Только MVP-стори (метка mvp); postMVP и Вакантные исключены",
                "Завершённые — факт; в работе — старт+остаток; бэклог — жадное назначение",
                "Зависимости фаз (BA∥ARC)→(DS∥BE)→FE внутри стори + явные Blocks",
                f"Хвост критпути: ресурс {crit_res}, окончание {crit_end_iso}",
            ],
        },
        "ganttAssumptions": {
            "dataSource": f"Jira B2BAPP {now_iso} (динамически)",
            "teamSource": "Confluence 1562745210 + сверка Jira assignee",
            "ganttType": "per_task_v3_mvp_only",
            "calendar": "Производственный календарь РФ",
            "vacancyHireDate": f"{VACANCY_HIRE_MIN.isoformat()} (FE-2, BE-1, QA-2)",
            "excludedFromGantt": "postMVP-стори и все Вакантные",
        },
        "epicProgress": epic_progress,
        "resourcePlan": resource_plan,
    }

    # ── Мёрж: заменяем ТОЛЬКО gantt-секции, остальное из старого файла ──────────
    new = dict(old)  # сохраняет usm, risks, questions, glossary, ... как есть
    new["ganttV2"] = ganttV2
    new["mvpScope"] = mvp_scope
    new["resourcePlan"] = resource_plan
    new["epicProgress"] = epic_progress
    new["totalIssues"] = total_issues
    new["team"] = team
    new["storyStatuses"] = story_st
    new["taskStatuses"] = task_st
    new["roleEstimates"] = role_est
    new["summary"] = {
        "epics": len(mvp_epics), "stories": len(mvp_stories), "tasks": len(mvp_tasks_it),
        "storiesDone": stories_done, "tasksDone": tasks_done,
        "hoursTotal": hours_total, "hoursSpent": hours_spent,
        "completionPct": completion,
        "scope": "MVP-only (метка mvp); postMVP и Вакантные исключены",
    }
    new["kpi"] = {
        "totalStories": len(mvp_stories), "totalTasks": len(mvp_tasks_it),
        "totalEpics": len(mvp_epics), "hoursTotal": hours_total, "hoursSpent": hours_spent,
        "completionPct": completion, "daysToDeadline": days_to_deadline,
        "criticalEnd": crit_end_iso,
        "mvpReachable": bool(end_date and end_date <= DEADLINE),
    }
    new["metrics"] = {
        "epicsTotal": len(mvp_epics), "storiesTotal": len(mvp_stories),
        "storiesDone": stories_done, "tasksTotal": len(mvp_tasks_it),
        "tasksDone": tasks_done, "hoursTotal": hours_total, "hoursSpent": hours_spent,
        "mvpStoriesIn": len(mvp_scope["inStories"]),
        "mvpStoriesOut": len(mvp_scope["outStories"]),
        "criticalPathEnd": crit_end_iso,
        "openQuestions": len([q for q in old.get("questions", [])
                              if str(q.get("status", "")).lower() not in ("закрыт", "closed", "решён", "решен")]),
    }
    new["criticalPathExplained"] = ganttV2["criticalPathExplained"]
    new["ganttAssumptions"] = ganttV2["ganttAssumptions"]

    # scopeGrowth: дописать точку сегодняшнего дня (не дублировать дату)
    sg = list(old.get("scopeGrowth", []))
    sg = [p for p in sg if p.get("date") != today.isoformat()]
    sg.append({"date": today.isoformat(), "epics": len(mvp_epics),
               "stories": len(mvp_stories), "tasks": len(mvp_tasks_it),
               "hoursTotal": hours_total, "note": "MVP-only"})
    new["scopeGrowth"] = sg

    # baselines: добавить новый, старые не трогать
    # baselines: один снимок на дату. Дедуп по id (как scopeGrowth),
    # иначе повторный прогон за день плодит дубль bl-ДД.ММ.ГГГГ.
    # Замечание Claude Code 22.08.2026.
    bl_id = f"bl-{today.isoformat()}"
    bl = [b for b in old.get("baselines", []) if b.get("id") != bl_id]
    bl.append({
        "id": bl_id,
        "ts": now_iso,
        "label": f"Refresh {today.strftime('%d.%m.%Y')} (MVP-only)",
        "criticalEnd": crit_end_iso,
        "items": [{"key": it["key"], "start": it["start"], "end": it["end"]}
                  for it in mvp_tasks_it],
    })
    new["baselines"] = bl

    # milestones: обновить статус вехи дедлайна
    ms = list(old.get("milestones", []))
    for m in ms:
        if m.get("date") == DEADLINE.isoformat():
            m["status"] = "done" if new["kpi"]["mvpReachable"] else "at_risk"
    new["milestones"] = ms

    new["refreshedAt"] = now_iso
    new["generatedAt"] = now_iso
    new["updated"] = today.strftime("%d.%m.%Y")

    # changelog
    cl = list(old.get("changelog", []))
    cl.append({"ts": now_iso, "area": "gantt",
               "text": f"gantt-прогон: Jira {total_issues} issue, {len(mvp_tasks_it)} MVP-задач, "
                       f"критпуть до {crit_end_iso}"})
    new["changelog"] = cl

    # ── Ассерты ────────────────────────────────────────────────────────────────
    errs = self_checks(items, ganttV2, mvp_scope, resource_plan, epic_progress)
    # накопление: счётчики не должны обрушиться против старого
    if old.get("metrics", {}).get("tasksTotal", 0) and len(mvp_tasks_it) < 0.5 * old["metrics"]["tasksTotal"]:
        errs.append(f"tasksTotal рухнул: было {old['metrics']['tasksTotal']}, стало {len(mvp_tasks_it)} — проверь mvp-метки/выгрузку")
    if not isinstance(new.get("usm"), (dict, type(None))):
        errs.append("usm повреждён при мёрже")

    if errs:
        print("САМОПРОВЕРКА НЕ ПРОШЛА:", file=sys.stderr)
        for e in errs:
            print("  •", e, file=sys.stderr)
        sys.exit(1)

    json.dump(new, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"OK. Записан {args.out}")
    print(f"  MVP: {len(mvp_epics)} эпиков, {len(mvp_stories)} стори, {len(mvp_tasks_it)} задач")
    print(f"  Часы: {hours_total} план / {hours_spent} списано ({completion}%)")
    print(f"  Критпуть до {crit_end_iso} (ресурс {crit_res}), "
          f"{'успеваем' if new['kpi']['mvpReachable'] else 'НЕ успеваем'} к 10.12.2026")
    print(f"  Ресурсов: {len(resources)} (реальных {sum(1 for r in resources if not r['vacant'])}, "
          f"вакансий {sum(1 for r in resources if r['vacant'])})")
    print(f"  scopeGrowth точек: {len(sg)}, baselines: {len(bl)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["gantt", "registries", "usm"])
    ap.add_argument("--jira")
    ap.add_argument("--team")
    ap.add_argument("--confluence")
    ap.add_argument("--usm-patch")
    ap.add_argument("--data", required=True, help="текущий public/data/data.json (для мёржа)")
    ap.add_argument("--out", required=True, help="куда писать (можно тот же файл)")
    args = ap.parse_args()

    if args.mode == "gantt":
        if not args.jira or not args.team:
            ap.error("режим gantt требует --jira и --team")
        run_gantt(args)
    else:
        print(f"Режим {args.mode} ещё не реализован (следующий шаг переработки).", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
