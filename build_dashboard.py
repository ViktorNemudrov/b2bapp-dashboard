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
import os
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

# Зависимости ролей ВНУТРИ стори (правка Виктора 03.10.2026, заменила строгую
# цепочку ARC→BA→DS→BE→FE→QA от 21.09): сначала аналитика (BA), она при
# необходимости подключает архитектуру (ARC); затем дизайн (DS) и бэкенд (BE)
# ПАРАЛЛЕЛЬНО; фронт (FE) — после готовности и дизайна, и бэка; QA берёт задачи
# по факту выполнения разработки (после BE и FE стори).
# ROLE_DEPS — от конца каких ролей стори ждёт задача роли; ROLE_PHASE — только
# порядок обработки очередей (зависимые роли считаются после тех, от кого
# зависят; DS и BE на одном уровне). ORG и DVO — параллельно всему.
ROLE_DEPS = {"BA": (), "ARC": ("BA",), "DS": ("BA", "ARC"), "BE": ("BA", "ARC"),
             "FE": ("BA", "ARC", "DS", "BE"), "QA": ("BA", "ARC", "BE", "FE")}
ROLE_PHASE = {"BA": 0, "ARC": 1, "DS": 2, "BE": 2, "FE": 3, "QA": 4}
PARALLEL_ROLES = {"ORG", "DVO", "OTHER"}  # не встраиваются в фазовую цепочку

# Спринты (Виктор 20.10.2026): каждый спринт ровно 2 недели, и в прошлом, и в
# будущем; Спринт 4 = 20.10.2026–03.11.2026, отсюда Спринт 0 = 25.08–08.09.
# Даты из Jira не берём: у будущих спринтов их нет, у закрытых они «грязные»
# (Спринт 0 в Jira 01.01–06.09, Спринт 1 закрыт 22.09 при плане 22.06).
SPRINT_ANCHOR = date(2026, 8, 25)   # начало Спринта 0
SPRINT_DAYS = 14
SPRINT_NAME_RE = re.compile(r"Спринт\s*(\d+)", re.I)
# Перерывы между спринтами: после Спринта 8 (15.12–29.12.2026) — новогодние
# каникулы, Спринт 9 начинается 12.01.2027 (так в «Плане ручном», Confluence
# 2666206915, 26.10.2026). Ключ — номер спринта ПОСЛЕ которого перерыв, дни.
SPRINT_GAP_AFTER = {8: 14}

# Спринтовая модель ганта (Виктор 26.10.2026): задача живёт в спринтах. Внутри
# спринта задачи исполнителя идут друг за другом по часам; бэклог без спринта
# раскладывается по будущим спринтам по «Плану ручному» с учётом ёмкости.
# Бек 1 = Попов, Бек 2 = Григоркин; остальные роли по одному (аналитики — по
# владельцу сценария в плане).
MANUAL_BE = {"BE1": "попов", "BE2": "григоркин"}

# Этапы сценария для упрощённого вида (роль задачи → этап). ARC относится к
# аналитике; ORG/DVO/OTHER в этапы не входят (Виктор 20.10.2026).
STAGES = (("AN", "Аналитика"), ("DS", "Дизайн"), ("BE", "Бэк"), ("FE", "Фронт"), ("QA", "QA"))
ROLE_STAGE = {"BA": "AN", "ARC": "AN", "DS": "DS", "BE": "BE", "FE": "FE", "QA": "QA"}
MANDATORY_STAGES = ("AN", "BE", "QA")   # Дизайн и Фронт — опциональны
SCENARIO_PREFIX_RE = re.compile(r"^\s*(?:\d+\.\s*)?((?:MD|OB|RB|PL|PK)\d+|NAI|IB|B2C)[.\s]")
SCENARIO_LABEL_RE = re.compile(r"^(?:MD|OB|RB|PL|PK)\d+$")

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

def sprint_start(n: int) -> date:
    gap = sum(g for k, g in SPRINT_GAP_AFTER.items() if n > k)
    return SPRINT_ANCHOR + timedelta(days=SPRINT_DAYS * n + gap)

def sprint_end(n: int) -> date:
    """Последний день спринта = через 2 недели от старта (20.10–03.11 — так
    называет даты Виктор): без перерыва это день старта следующего, граница
    принадлежит обоим соседям."""
    return sprint_start(n) + timedelta(days=SPRINT_DAYS)

def sprint_of_date(d: date) -> int:
    """В каком спринте закончится работа с датой окончания d (граница —
    в уходящий спринт: 20.10 = последний день Спринта 3; дни перерыва —
    в спринт перед ним). До Спринта 0 → -1."""
    if d <= SPRINT_ANCHOR:
        return -1
    n = 0
    while sprint_start(n + 1) < d:
        n += 1
    return n

def sprint_index(d: date) -> int:
    """Текущий спринт на дату d: последний начавшийся (20.10 → Спринт 4)."""
    n = 0
    while sprint_start(n + 1) <= d:
        n += 1
    return n

def sprint_workdays(n: int):
    """Рабочие дни спринта: [старт, конец) — граничный день отдаём следующему."""
    return list(workdays_between(sprint_start(n), sprint_end(n) - timedelta(days=1)))

def sprint_calendar(until: date, today: date, jira_sprints):
    """Спринты 0..N, пока не покроют until. state по today (closed/active/
    future); jiraState — как в Jira, для справки."""
    jira_by_n = {}
    for s in jira_sprints or []:
        m = SPRINT_NAME_RE.search(s.get("name") or "")
        if m:
            jira_by_n[int(m.group(1))] = s
    last = max(sprint_of_date(until), max(jira_by_n, default=0), sprint_of_date(today))
    out = []
    for n in range(0, last + 1):
        st, en = sprint_start(n), sprint_end(n)
        state = "closed" if en <= today else ("active" if st <= today else "future")
        js = jira_by_n.get(n) or {}
        out.append({"n": n, "name": f"Спринт {n}", "short": f"С{n}",
                    "start": st.isoformat(), "end": en.isoformat(), "state": state,
                    **({"jiraState": js.get("state"), "jiraId": js.get("id")} if js else {})})
    return out

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
    # "waiting for release" — реальный статус из Jira (не было в тестовых
    # дампах): разработка и тестирование завершены (remainingEstimate=0),
    # ждёт только релиза — по сути done, а не непочатый бэклог.
    if s in ("завершена", "готово", "done", "closed", "resolved", "waiting for release"):
        return "done"
    if s in ("в работе", "разработка", "review", "анализ", "in progress",
              "ready for testing", "тестирование", "review ready"):
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
    # Спринты задачи (customfield_10905, в дампе — разобранный список sprints[]).
    # closedSprint — номер последнего ЗАКРЫТОГО в Jira спринта задачи: в нём она
    # и «завершилась» (незакрытые задачи переезжают в следующий спринт и
    # закрытый остаётся в истории). lastSprint — последний вообще.
    sprint_nums, closed_nums = [], []
    for s in f.get("sprints") or []:
        m = SPRINT_NAME_RE.search(s.get("name") or "")
        if not m:
            continue
        sprint_nums.append(int(m.group(1)))
        if (s.get("state") or "").upper() == "CLOSED":
            closed_nums.append(int(m.group(1)))
    return {
        "key": raw.get("key"),
        "type": itype,
        "summary": summary,
        "lastSprint": max(sprint_nums) if sprint_nums else None,
        "closedSprint": max(closed_nums) if closed_nums else None,
        "sprints": sorted(set(sprint_nums)),
        "status": (f.get("status") or {}).get("name", ""),
        # выгрузка кладёт только displayName (первые два слова) — по фамилии
        # сопоставляем с ресурсом (спринтовая модель 26.10.2026)
        "assignee": assignee.get("name") or assignee.get("key") or assignee.get("displayName") or "",
        "created": parse_dt(f.get("created")),
        # «Дата начала» (customfield_18100) — фактическое начало работы; у стори и
        # эпиков = самая ранняя у их задач (правило Виктора 11.10.2026, проверка
        # check_jira_rollup.py). Начало задачи на ганте берётся отсюда, не из created.
        "startDate": parse_dt(f.get("customfield_18100")),
        "jiraStarted": ((f.get("status") or {}).get("name", "") or "").strip().lower() != "бэклог",
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

def plan_gantt(issues, resources, today=None, manual=None, story_scenario=None):
    """
    Возвращает items[] (epic+story+task) с датами, ресурсами, критпутём.
    Планируем ТОЛЬКО MVP (метка mvp у стори) + их задачи. Вакантные (issue и
    ресурсы) исключены. Завершённые — факт. В работе — факт-старт + остаток.
    Бэклог — жадное назначение по очередям ресурсов без простоя, приоритет =
    приоритет эпика/стори.
    """
    if today is None:
        today = date.today()
    issues = [i for i in issues if not i["vacant"]]
    by_key = {i["key"]: i for i in issues}

    epics = {i["key"]: i for i in issues if i["type"] == "epic"}
    stories = {i["key"]: i for i in issues if i["type"] == "story"}
    tasks = [i for i in issues if i["type"] == "task"]

    # Метки "mvp" в Jira больше нет (Виктор 21.09.2026) — сам бэклог теперь
    # заранее прескоуплен: выгрузка берёт только задачи с оценкой под 10
    # согласованными эпиками (после чистки Леонида), так что скоуп = все
    # стори, которые реально пришли в дампе, без отдельного лейбл-фильтра.
    mvp_story_keys = set(stories.keys())
    mvp_tasks = [t for t in tasks if t["partParent"] in mvp_story_keys]

    # "Сироты": задача без Part-связи на стори вообще (или связанной со стори
    # вне скоупа) — реальный пробел в Jira (обнаружено 21.09.2026: 30 задач,
    # ~1257ч). Не выбрасываем — планируем НАПРЯМУЮ под эпик по customfield_10901
    # задачи (без стори-контекста, поэтому без фазовой зависимости внутри
    # стори — гейтить не по чему). Виктор попросит собрать список для
    # проставления Part-связей в Jira отдельно (значит "epicLink" у задачи
    # обязателен, иначе она и правда потеряна — таких на 21.09.2026 не было).
    orphan_tasks = [t for t in tasks
                    if t["partParent"] not in mvp_story_keys and t.get("epicLink") in epics]
    all_tasks = mvp_tasks + orphan_tasks

    # Реальные (не вакантные) ресурсы — вакантные ставки-гипотезы НЕ участвуют
    # в назначении задач вообще (Виктор 21.09.2026: "считаем, что их не будет").
    real_resources = [r for r in resources if not r.get("vacant")]

    # Очереди ресурсов: следующая свободная дата по каждому ресурсу — не раньше
    # today, иначе бэклог-задача может "начаться" в прошлом (см. баг
    # 21.09.2026: без этого пола BA/DS/ARC планировались от даты найма
    # ресурса, а не от текущей даты, и жадный алгоритм в первую очередь
    # выбирал того, кто "свободен раньше" в прошлом — второй ресурс роли
    # (например, Шевченко) вообще не получал задач, потому что коллега,
    # нанятый раньше, был вечно "свободнее" на всём этом ложном отрезке).
    res_free = {r["id"]: max(parse_dt(r["from"]) or today, today) for r in real_resources}
    res_by_role = defaultdict(list)
    for r in real_resources:
        res_by_role[r["role"]].append(r)

    def pick_resource(role, earliest):
        """Ресурс нужной роли (реальный, не вакантный), который освободится раньше всех."""
        pool = res_by_role.get(role) or res_by_role.get("OTHER") or real_resources
        best = min(pool, key=lambda r: max(res_free[r["id"]], parse_dt(r["from"]) or earliest, earliest))
        return best

    planned = {}   # key → {start,end,resource,...}

    # Приоритет: ЭПИК (числовой префикс в summary самого эпика, а не дата
    # создания и не префикс стори) → приоритет стори внутри эпика → приоритет
    # самой задачи → ключ. Правка Виктора 21.09.2026 — раньше сортировка шла
    # только по префиксу стори, который локальный на каждый эпик (снова
    # начинается с "1." в каждом эпике), из-за чего порядок эпиков получался
    # произвольным (фактически — по порядку в jira_dump.json).
    def story_prio(t):
        s = stories.get(t["partParent"])
        if s:
            return (resolve_epic_priority(epics.get(s.get("epicLink"))), s["priority"])
        # Сирота: приоритет эпика напрямую по epicLink задачи; своего
        # "приоритета стори" нет — используем приоритет самой задачи как
        # tie-break (обычно 9999, т.е. после обычных стори этого эпика).
        return (resolve_epic_priority(epics.get(t.get("epicLink"))), t["priority"])
    def prio_key(t):
        return (story_prio(t), t["priority"], t["key"])

    # ═════════════════════════════════════════════════════════════════════════
    # Спринтовая модель (Виктор 26.10.2026; заменила ready-queue с 22.09).
    # Раньше начатая задача рисовалась от «Даты начала» в Jira до конца её
    # остатка в очереди планировщика — 2-часовая задача Самойло тянулась с
    # сентября до января, и всё у исполнителя выглядело параллельным. Теперь:
    #  1. Задача из спринтов Jira (факт и обязательство команды) — в своём
    #     последнем спринте не позже текущего; завершённая (в т.ч. «Waiting for
    #     release») — в спринте, где завершилась; переходившая из спринта в
    #     спринт — бар от первого её спринта. Спринт 0 — как раньше, по факту.
    #  2. Бэклог без спринта — в будущие спринты (с текущий+1) по «Плану
    #     ручному» (сценарий → этап → спринт; Бек 1/2 → Попов/Григоркин) с
    #     учётом ёмкости исполнителя (2 недели × 8ч × FTE); не влезло — в
    #     следующий спринт. Зависимости ролей стори — на уровне спринтов (Фронт
    #     не раньше спринта Бэка и Дизайна и т.д., тот же спринт — можно).
    #  3. Внутри спринта задачи исполнителя идут подряд по часам: готовые →
    #     в работе → остальные по приоритету; перегруз сжимается в спринт.
    # ═════════════════════════════════════════════════════════════════════════
    def st_key_of(t):
        # None у "сирот" (нет реальной стори): иначе несколько разных сирот
        # синхронизировались бы на один ключ None и ложно гейтили друг друга.
        return t["partParent"] if t["partParent"] in stories else None

    manual = manual or {}
    story_scenario = story_scenario or {}
    plan_cells = {r["code"]: {int(k): v for k, v in r["cells"].items()} for r in manual.get("rows", [])}
    plan_owner = {r["code"]: (r.get("owner") or "").lower() for r in manual.get("rows", [])}
    cur = sprint_index(today)
    nxt = cur + 1
    res_by_id = {r["id"]: r for r in real_resources}
    res_by_surname = {r["name"].split()[0].lower(): r for r in real_resources}

    def res_of_assignee(t):
        """Исполнитель из Jira — только если его роль = роль задачи (задачи
        [FE]/[BE] в тестировании висят на тестировщике, это не его работа)."""
        a = (t.get("assignee") or "").split()
        r = res_by_surname.get(a[0].lower()) if a else None
        if r and (r["role"] == t["role"] or {r["role"], t["role"]} <= {"BA", "ARC"}):
            return r
        return None

    cap_cache = {}
    def cap(r, n):
        if (r["id"], n) not in cap_cache:
            frm = parse_dt(r["from"]) or SPRINT_ANCHOR
            cap_cache[(r["id"], n)] = sum(1 for d in sprint_workdays(n) if d >= frm) * HOURS_PER_DAY * r["fte"]
        return cap_cache[(r["id"], n)]

    load = defaultdict(float)            # (rid, n) → часы в спринте
    segs = defaultdict(list)             # (rid, n) → [(order, key, hours)]
    meta = {}                            # key → {first, last, res, cat, src}
    story_sprint = defaultdict(dict)     # story → role → последний спринт

    def note_story(t, last):
        st = st_key_of(t)
        if st is not None and t["role"]:
            story_sprint[st][t["role"]] = max(story_sprint[st].get(t["role"], -1), last)

    def scenario_of(t):
        return story_scenario.get(t["partParent"]) if t["partParent"] in stories else None

    def plan_sprints(t):
        """Спринты этапа задачи по «Плану ручному» и какой бэк там назван."""
        cells = plan_cells.get(scenario_of(t)) or {}
        stage = ROLE_STAGE.get(t["role"])
        out, be = [], None
        for n, sts in sorted(cells.items()):
            if stage == "BE":
                hit = [s for s in sts if s in ("BE", "BE1", "BE2")]
                if hit:
                    out.append(n)
                    be = be or next((s for s in hit if s != "BE"), None)
            elif stage and stage in sts:
                out.append(n)
        return out, be

    def choose_res(t, n, be=None):
        r = res_of_assignee(t)
        if r:
            return r
        if t["role"] == "BE" and be in MANUAL_BE:
            r = res_by_surname.get(MANUAL_BE[be])
            if r:
                return r
        pool = res_by_role.get(t["role"]) or res_by_role.get("OTHER") or real_resources
        if t["role"] == "BA":
            own = plan_owner.get(scenario_of(t)) or ""
            mine = [r for r in pool if r["name"].split()[0].lower()[:5] in own]
            if mine:
                return mine[0]
        return min(pool, key=lambda r: (load[(r["id"], n)] / max(cap(r, n), 1), r["id"]))

    def hours_of(t, cat):
        if cat == "in_progress":
            return max(t["estimateH"] - t["spentH"], 1)
        return max(t["estimateH"], 1)

    # QA встроен в задачи [FE]/[BE] (Виктор 26.10.2026): оценка = 70% разработка
    # + 30% тестирование, в конце задача переходит к тестировщику (статусы
    # «Ready for testing»/«Тестирование»). Разработчику — 70% часов, QA — 30%
    # в том же спринте; задача в статусе тестирования целиком у QA (остаток =
    # 30% оценки). Отдельных задач [QA] пока нет.
    qa_res = (res_by_role.get("QA") or [None])[0]
    def is_dev(t):
        return t["role"] in ("FE", "BE") and qa_res is not None
    def in_qa(t):
        return (t["status"] or "").strip().lower() in QA_STATUSES
    def add_qa_load(n, h):
        if qa_res is not None and h > 0:
            load[(qa_res["id"], n)] += h

    # ── 1. Задачи со спринтами Jira + начатые: факт / обязательство ──────────
    backlog, committed = [], []
    for t in all_tasks:
        cat = status_category(t["status"])
        sp = t.get("sprints") or []
        hist = [n for n in sp if n <= cur]
        if cat == "done":
            fact_end = t["resolutiondate"] or t["updated"] or t["startDate"] or t["created"] or date(2026, 1, 1)
            n = max(hist) if hist else None
            # Спринт 0 и закрытые до начала своего спринта (Спринт 0 в Jira
            # собрал работу с января) — по фактическим датам, как раньше.
            if n is None or n == 0 or fact_end < sprint_start(n):
                res = res_of_assignee(t) or choose_res(t, sprint_of_date(fact_end))
                planned[t["key"]] = {"start": min(t["startDate"] or t["created"] or fact_end, fact_end),
                                     "end": fact_end, "resource": res["id"], "category": cat,
                                     "planStart": None, "src": "fact"}
                note_story(t, sprint_of_date(fact_end))
                continue
            first = min([x for x in hist if x >= 1] or [n])
            res = choose_res(t, n)
            h, order = hours_of(t, cat), (0, fact_end.isoformat(), t["key"])
            if is_dev(t):
                add_qa_load(n, h * QA_SHARE)
                h *= 1 - QA_SHARE
        elif sp or cat == "in_progress":
            committed.append(t)
            continue
        else:
            backlog.append(t)
            continue
        load[(res["id"], n)] += h
        segs[(res["id"], n)].append((order, t["key"], h))
        meta[t["key"]] = {"first": first, "last": n, "res": res["id"], "cat": cat, "src": "jira"}
        note_story(t, n)

    def allocate(t, res, n, h, order):
        """Положить h часов в спринты с n по ёмкости исполнителя; не влезло — в
        следующий. Возвращает (первый, последний) спринт."""
        first = None
        while h > 1e-6 and n < 200:
            free = cap(res, n) - load[(res["id"], n)]
            if free < 0.5:
                n += 1
                continue
            take = min(h, free)
            load[(res["id"], n)] += take
            segs[(res["id"], n)].append((order, t["key"], take))
            first = n if first is None else first
            h -= take
            if h > 1e-6:
                n += 1
        return first, n

    # Незавершённые из спринтов Jira (текущий/будущие; из закрытых — перенесены
    # в текущий). Спринт в Jira — обязательство команды, но больше ёмкости в
    # спринт не влезет: остаток уходит в следующие спринты (src=jira+), иначе
    # прогноз молча оптимистичен (С4 у фронта на 26.10.2026 — 296ч при 80ч).
    # Порядок: в работе → остальные по приоритету.
    for t in sorted(committed, key=lambda t: (max(max(t.get("sprints") or [cur]), cur),
                                              status_category(t["status"]) != "in_progress", prio_key(t))):
        cat = status_category(t["status"])
        sp = t.get("sprints") or []
        n = max(sp) if sp and max(sp) >= cur else cur
        order = (1 if cat == "in_progress" else 2, prio_key(t))
        if is_dev(t) and in_qa(t):        # разработка готова — тестирует QA
            res = qa_res
            f, last = allocate(t, res, n, max(t["estimateH"] * QA_SHARE, 1), order)
        elif is_dev(t):
            res = choose_res(t, n)
            h = hours_of(t, cat)
            f, last = allocate(t, res, n, h * (1 - QA_SHARE), order)
            add_qa_load(last, h * QA_SHARE)
        else:
            res = choose_res(t, n)
            f, last = allocate(t, res, n, hours_of(t, cat), order)
        # Бар от первого спринта — только если задача реально переходила из
        # ЗАКРЫТОГО спринта; перенос по ёмкости начинается там, куда легла.
        first = min([x for x in sp if 1 <= x < cur] + [f])
        meta[t["key"]] = {"first": first, "last": last, "res": res["id"], "cat": cat,
                          "src": "jira" if last == n else "jira+"}
        note_story(t, last)

    # ── 2. Бэклог без спринта → будущие спринты по «Плану ручному» ──────────
    def phase_of(t):
        return ROLE_PHASE.get(t["role"], -1)
    for t in sorted(backlog, key=lambda t: (phase_of(t), prio_key(t))):
        cat = status_category(t["status"])
        ps, be = plan_sprints(t)
        later = [n for n in ps if n >= nxt]
        n = later[0] if later else nxt
        src = "manual" if ps else "auto"
        st = st_key_of(t)
        if st is not None:
            for dr in ROLE_DEPS.get(t["role"], ()):
                n = max(n, story_sprint[st].get(dr, -1))
        for dk in t["blocksDeps"]:
            if dk in meta:
                n = max(n, meta[dk]["last"])
        res = choose_res(t, n, be)
        h = hours_of(t, cat)
        if is_dev(t):
            first, n = allocate(t, res, n, h * (1 - QA_SHARE), (3, prio_key(t)))
            add_qa_load(n, h * QA_SHARE)
        else:
            first, n = allocate(t, res, n, h, (3, prio_key(t)))
        meta[t["key"]] = {"first": first, "last": n, "res": res["id"], "cat": cat, "src": src}
        note_story(t, n)

    # ── 3. Раскладка внутри спринта: подряд по часам ─────────────────────────
    seg_dates = defaultdict(list)        # key → [(n, start, end)]
    for (rid, n), lst in segs.items():
        days = sprint_workdays(n) or [next_workday(sprint_start(n))]
        per_day = HOURS_PER_DAY * res_by_id[rid]["fte"]
        need = sum(h for _, _, h in lst) / per_day
        k = min(1.0, len(days) / need) if need else 1.0   # перегруз — сжимаем в спринт
        off = 0.0
        for order, key, h in sorted(lst):
            dur = h / per_day * k
            si = min(int(off + 1e-9), len(days) - 1)
            ei = min(max(si, -(-int(round((off + dur) * 1000)) // 1000) - 1), len(days) - 1)
            seg_dates[key].append((n, days[si], days[ei]))
            off += dur
    for key, m in meta.items():
        sd = sorted(seg_dates[key])
        start, end = sd[0][1], sd[-1][2]
        if m["first"] < sd[0][0]:   # переходила из спринта в спринт — бар от первого спринта
            start = next_workday(sprint_start(m["first"]))
        planned[key] = {"start": start, "end": end, "resource": m["res"], "category": m["cat"],
                        "planStart": None, "src": m["src"], "sprintFrom": m["first"], "sprintTo": m["last"]}
    sprint_load = {f"{rid}|{n}": {"hours": round(h, 1), "capacity": round(cap(res_by_id[rid], n), 1)}
                   for (rid, n), h in load.items() if h > 0}

    # ── Сборка items[] ────────────────────────────────────────────────────────
    items = []
    # задачи, привязанные к стори
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
            **({"planStart": p["planStart"].isoformat()} if p.get("planStart") else {}),
            **({"actualStart": t["startDate"].isoformat()} if t["jiraStarted"] and t["startDate"] and p["category"] != "done" else {}),
            "started": bool(t["jiraStarted"]),
            "resource": p["resource"], "onCriticalPath": False,
            "deps": t["blocksDeps"],
        })
    # задачи-сироты — нет Part-связи на стори в Jira, планируем напрямую
    # под эпик (parent=epic), чтобы часы/сроки не терялись молча (см. правку
    # 21.09.2026 про orphan_tasks). Список для проставления связей в Jira —
    # выводится self_checks-предупреждением ниже, не падает сборка.
    for t in orphan_tasks:
        p = planned.get(t["key"])
        if not p:
            continue
        items.append({
            "key": t["key"], "type": "task", "parent": t["epicLink"],
            "epic": t["epicLink"],
            "summary": t["summary"], "role": t["role"], "priority": t["priority"],
            "estimateH": t["estimateH"], "spentH": t["spentH"],
            "status": t["status"], "category": p["category"],
            "start": p["start"].isoformat(), "end": p["end"].isoformat(),
            **({"planStart": p["planStart"].isoformat()} if p.get("planStart") else {}),
            **({"actualStart": t["startDate"].isoformat()} if t["jiraStarted"] and t["startDate"] and p["category"] != "done" else {}),
            "started": bool(t["jiraStarted"]),
            "resource": p["resource"], "onCriticalPath": False,
            "deps": t["blocksDeps"], "orphan": True,
        })
    # Спринт задачи по спринтовой модели: sprint — в котором заканчивается,
    # sprintFrom — первый; planSource — откуда спринт: jira (спринт в Jira),
    # manual («План ручной»), auto (плана нет — ближайший свободный), fact (С0/факт).
    for it in items:
        p = planned.get(it["key"]) or {}
        if p.get("sprintTo") is not None:
            it["sprint"], it["sprintFrom"] = p["sprintTo"], p["sprintFrom"]
        else:
            it["sprint"] = sprint_of_date(date.fromisoformat(it["end"]))
        it["planSource"] = p.get("src")
    # стори (агрегат из их задач)
    for sk in mvp_story_keys:
        s = stories[sk]
        kids = [it for it in items if it["parent"] == sk]
        if kids:
            start = min(it["start"] for it in kids)
            end = max(it["end"] for it in kids)
        else:
            start = (s["startDate"] or s["created"] or date(2026, 1, 1)).isoformat()
            end = start
        # Стори не может быть «не начата», если хоть одна её задача в Jira не в
        # «Бэклог» (правило Виктора 11.10.2026).
        cat = "done" if kids and all(it["category"] == "done" for it in kids) \
              else ("in_progress" if any(it["category"] != "backlog" or it.get("started") for it in kids) else "backlog")
        items.append({
            "key": sk, "type": "story", "parent": s["epicLink"], "epic": s["epicLink"],
            "summary": s["summary"], "priority": s["priority"],
            "estimateH": sum(it["estimateH"] for it in kids),
            "spentH": sum(it["spentH"] for it in kids),
            "start": start, "end": end, "category": cat,
            "started": cat != "backlog",
            "onCriticalPath": False, "deps": [],
        })
    # эпики (агрегат из их стори + прямых задач-сирот под эпиком, у которых
    # нет стори — иначе их часы/сроки не попали бы в итог эпика вообще).
    epic_keys = ({s["epicLink"] for s in [stories[k] for k in mvp_story_keys] if s.get("epicLink")}
                 | {t["epicLink"] for t in orphan_tasks if t.get("epicLink")})
    for ek in epic_keys:
        e = epics.get(ek)
        kids = [it for it in items if it["epic"] == ek
                and (it["type"] == "story" or (it["type"] == "task" and it.get("orphan")))]
        if not kids:
            continue
        # Начало эпика — по стори с задачами (у пустых стори дата условная:
        # «Дата начала» или created), иначе эпик «начинается» раньше реальной работы.
        timed = [it for it in kids if it["type"] == "task" or it.get("estimateH")] or kids
        start = min(it["start"] for it in timed)
        end = max(it["end"] for it in kids)
        cat = "done" if all(it["category"] == "done" for it in kids) \
              else ("in_progress" if any(it["category"] != "backlog" or it.get("started") for it in kids) else "backlog")
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

    orphan_report = [{"key": t["key"], "epic": t["epicLink"], "summary": t["summary"],
                       "estimateH": t["estimateH"]} for t in orphan_tasks]
    return items, end_date, crit_res, mvp_story_keys, orphan_report, sprint_load

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
# ─────────────────────────────────────────────────────────────────────────────
#  Сценарии (реестр Confluence 2356754448, запрос Виктора 20.10.2026)
# ─────────────────────────────────────────────────────────────────────────────
def load_scenarios(path):
    if not path or not os.path.exists(path):
        return None
    return json.load(open(path, encoding="utf-8"))

def assign_scenarios(items, issues, reg):
    """Каждой стори — ровно один сценарий; задача наследует сценарий стори.
    Источник по убыванию надёжности: метка Jira (OB1, PL9…) → префикс названия
    («PK1. Как…») → таблица «Структура и оценка» реестра → ручная логическая
    привязка storyOverrides → PLATFORM. Задачи-сироты (без стори) → PLATFORM."""
    known = {s["code"] for s in reg["scenarios"]}
    by_key = {i["key"]: i for i in issues}
    conf = reg.get("confluenceStories") or {}
    over = reg.get("storyOverrides") or {}
    story_sc = {}
    for it in items:
        if it["type"] != "story":
            continue
        src = by_key.get(it["key"]) or {}
        code, how = None, None
        labels = [l for l in (src.get("labels") or []) if SCENARIO_LABEL_RE.match(l) and l in known]
        if labels:
            code, how = labels[0], "метка Jira"
        if not code:
            m = SCENARIO_PREFIX_RE.match(src.get("summary") or "")
            if m and m.group(1) in known:
                code, how = m.group(1), "префикс названия"
        if not code:
            cands = [c for c in conf.get(it["key"], []) if c in known]
            if cands:
                code, how = cands[0], "реестр Confluence"
        if not code and it["key"] in over and over[it["key"]]["code"] in known:
            code, how = over[it["key"]]["code"], "логическая привязка: " + over[it["key"]]["why"]
        if not code:
            code, how = "PLATFORM", "не привязана — по умолчанию в «Платформу»"
        it["scenario"], it["scenarioSource"] = code, how
        story_sc[it["key"]] = code
    for it in items:
        if it["type"] == "task":
            it["scenario"] = story_sc.get(it["parent"], "PLATFORM")

QA_SHARE = 0.30          # доля QA внутри оценки задач [FE]/[BE]: 70% разработка, 30% QA (Виктор 26.10.2026; было 35% с 20.10)
QA_STATUSES = {"ready for testing", "тестирование"}   # разработка готова, идёт QA

def stage_segments(tasks):
    """Отрезки этапов из задач. QA сидит внутри задач [FE]/[BE]: последние 30%
    оценки — тестирование, после реализации задача сама уходит на QA. Поэтому
    задача FE/BE даёт два отрезка: разработка (первые 70% её срока) и QA
    (остальные 30%). Статус «Ready for testing»/«Тестирование» — разработка
    готова, QA в работе. Отдельные задачи [QA] — целиком в этап QA."""
    out = []
    for t in tasks:
        sid = ROLE_STAGE.get(t["role"])
        if not sid:
            continue
        s, e = date.fromisoformat(t["start"]), date.fromisoformat(t["end"])
        cat = t["category"]
        dev_cat = cat if cat != "backlog" or not t.get("started") else "in_progress"
        if sid in ("FE", "BE"):
            mid = s + timedelta(days=round((e - s).days * (1 - QA_SHARE)))
            in_qa = (t.get("status") or "").strip().lower() in QA_STATUSES
            out.append({"stage": sid, "start": t["start"], "end": mid.isoformat(),
                        "h": t["estimateH"] * (1 - QA_SHARE),
                        "cat": "done" if in_qa else dev_cat, "key": t["key"]})
            out.append({"stage": "QA", "start": mid.isoformat(), "end": t["end"],
                        "h": t["estimateH"] * QA_SHARE, "embedded": True,
                        "cat": "done" if cat == "done" else ("in_progress" if in_qa else "backlog"),
                        "key": t["key"]})
        else:
            out.append({"stage": sid, "start": t["start"], "end": t["end"], "h": t["estimateH"],
                        "cat": dev_cat, "key": t["key"]})
    return out

def calc_scenarios(items, reg, today):
    """Агрегат по сценарию + этапы (Аналитика/Дизайн/Бэк/Фронт/QA) для
    упрощённого вида. Прошлое — факт, будущее — прогноз планировщика (даты
    задач уже посчитаны в plan_gantt). Фронт только рисует."""
    tasks = [it for it in items if it["type"] == "task"]
    stories = [it for it in items if it["type"] == "story"]
    out = []
    for s in reg["scenarios"]:
        code = s["code"]
        kt = [t for t in tasks if t.get("scenario") == code]
        ks = [st["key"] for st in stories if st.get("scenario") == code]
        if not kt and not ks:
            out.append({**{k: s.get(k) for k in ("order", "contour", "code", "name", "priority", "epic")},
                        "registryStatus": s.get("status"), "stories": [], "tasks": 0,
                        "estimateH": 0, "spentH": 0, "category": "empty", "stages": [],
                        "missingStages": list(MANDATORY_STAGES),
                        "current": "нет задач в Jira"})
            continue
        timed = [t for t in kt if t.get("start") and t.get("end")]
        cat = ("done" if kt and all(t["category"] == "done" for t in kt) else
               "in_progress" if any(t["category"] != "backlog" or t.get("started") for t in kt) else "backlog")
        segs = stage_segments(timed)
        stages = []
        for sid, sname in STAGES:
            st_t = [g for g in segs if g["stage"] == sid]
            if not st_t:
                continue
            est = round(sum(g["h"] for g in st_t))
            done_h = round(sum(g["h"] for g in st_t if g["cat"] == "done"))
            # частично готовый этап (часть отрезков done, остальные не начаты) — «в работе»
            scat = ("done" if all(g["cat"] == "done" for g in st_t) else
                    "in_progress" if any(g["cat"] in ("in_progress", "done") for g in st_t) else "backlog")
            start = min(g["start"] for g in st_t)
            end = max(g["end"] for g in st_t)
            end_sp = sprint_of_date(date.fromisoformat(end))
            # День-граница (20.10) — и начало С4, и конец С3: не даём началу
            # этапа оказаться в спринте позже его конца.
            start_sp = min(sprint_of_date(date.fromisoformat(start) + timedelta(days=1)), end_sp)
            stages.append({"id": sid, "name": sname, "start": start, "end": end,
                           "estimateH": est, "doneH": done_h, "tasks": len(st_t),
                           "tasksDone": sum(1 for g in st_t if g["cat"] == "done"),
                           "category": scat, "startSprint": start_sp, "endSprint": end_sp,
                           **({"embeddedQaH": round(sum(g["h"] for g in st_t if g.get("embedded")))}
                              if sid == "QA" else {})})
        # Аналитика, Бэк и QA обязательны для каждого сценария, Дизайн и Фронт —
        # по необходимости (Виктор 20.10.2026). Нет задач обязательного этапа в
        # Jira — показываем явно: прогноз готовности без него оптимистичен.
        have = {st["id"] for st in stages}
        missing = [sid for sid in MANDATORY_STAGES if sid not in have]
        active = [st["name"] for st in stages if st["category"] == "in_progress"]
        if cat == "done":
            current = "Готово"
        elif active:
            current = ", ".join(active)
        else:
            nxt = next((st["name"] for st in stages if st["category"] != "done"), None)
            current = f"ожидает: {nxt}" if nxt else "—"
        end = max((t["end"] for t in timed), default=None)
        start = min((t["start"] for t in timed), default=None)
        end_d = date.fromisoformat(end) if end else None
        out.append({
            **{k: s.get(k) for k in ("order", "contour", "code", "name", "priority", "epic")},
            "registryStatus": s.get("status"),
            "stories": ks, "tasks": len(kt),
            "tasksDone": sum(1 for t in kt if t["category"] == "done"),
            "estimateH": sum(t["estimateH"] for t in kt),
            "spentH": sum(t["spentH"] for t in kt),
            "start": start, "end": end, "category": cat,
            "onCriticalPath": any(t.get("onCriticalPath") for t in kt),
            "stages": stages, "current": current, "missingStages": missing,
            "readySprint": sprint_of_date(end_d) if end_d else None,
            "onTime": bool(end_d and end_d <= DEADLINE),
        })
    return out

def calc_sprint_stats(items, reg, n):
    """Задачи спринта n по сценариям (для страницы «Статус для руководства»):
    сколько задач было в спринте, сколько в нём завершено (в т.ч. Waiting for
    release), в тестировании, в работе."""
    names = {s["code"]: s.get("name") for s in (reg or {}).get("scenarios", [])}
    order = {s["code"]: i for i, s in enumerate((reg or {}).get("scenarios", []))}
    by = defaultdict(list)
    for t in items:
        if t["type"] == "task" and t.get("sprint") is not None and                 (t.get("sprintFrom") if t.get("sprintFrom") is not None else t["sprint"]) <= n <= t["sprint"]:
            by[t.get("scenario") or "PLATFORM"].append(t)
    out = []
    for code, ts in by.items():
        out.append({"code": code, "name": names.get(code, code), "tasks": len(ts),
                    "done": sum(1 for t in ts if t["category"] == "done" and t["sprint"] == n),
                    "inQa": sum(1 for t in ts if t["category"] != "done"
                                and (t.get("status") or "").strip().lower() in QA_STATUSES),
                    "inProgress": sum(1 for t in ts if t["category"] == "in_progress"
                                      and (t.get("status") or "").strip().lower() not in QA_STATUSES),
                    "estimateH": sum(t["estimateH"] for t in ts)})
    return sorted(out, key=lambda x: order.get(x["code"], 999))


def calc_manual_plan(mp, items, resources, reg=None, cur_sprint=0):
    """«План ручной» для упрощённого вида «Этапы по сценариям»: план аналитиков
    по спринтам как есть + статус этапа по Jira (для цвета: зелёный — только
    если все задачи этапа «Завершена»/«Waiting for release»). QA встроен в
    задачи Фронта/Бэка (30% оценки), поэтому этап QA = задачи [QA] + [FE] +
    [BE]: в работе — есть задачи в «Ready for testing»/«Тестирование»."""
    tasks = [it for it in items if it["type"] == "task"]
    cs = (reg or {}).get("completedScenarios") or {}
    completed_codes, completed_why = set(cs.get("codes") or []), cs.get("why")

    def stat(ts):
        done = sum(1 for t in ts if t["category"] == "done")
        cat = ("done" if done == len(ts) else
               "in_progress" if any(t["category"] != "backlog" or t.get("started") for t in ts) else "backlog")
        return {"category": cat, "tasks": len(ts), "done": done,
                "estimateH": sum(t["estimateH"] for t in ts),
                "sprints": sorted({t["sprint"] for t in ts if t.get("sprint") is not None})}
    rows = []
    for r in mp.get("rows", []):
        kt = [t for t in tasks if t.get("scenario") == r["code"]]
        be = [t for t in kt if t["role"] == "BE"]
        by = {"AN": [t for t in kt if t["role"] in ("BA", "ARC")],
              "DS": [t for t in kt if t["role"] == "DS"],
              "BE": be,
              # Бэк 1 / Бэк 2 в плане — кто делает, но в Jira по человеку не отличить:
              # в тестировании исполнитель — QA, а resource планировщика переезжает
              # на QA. Поэтому этап «Бэк 1/2» = все [BE] сценария (27.10.2026,
              # так же считает проверка P4 аудита в чате).
              "BE1": be,
              "BE2": be,
              "FE": [t for t in kt if t["role"] == "FE"],
              "QA": [t for t in kt if t["role"] in ("QA", "FE", "BE")]}
        jira = {k: stat(v) for k, v in by.items() if v}
        if "QA" in jira:   # QA начинается, только когда задача ушла в тестирование
            q = by["QA"]
            if jira["QA"]["category"] != "done":
                jira["QA"]["category"] = "in_progress" if any(
                    (t.get("status") or "").strip().lower() in QA_STATUSES for t in q) else "backlog"
        # Состояние этапа для цвета (Виктор 26.10.2026): done — закрыт в Jira;
        # passed — начался следующий этап (Аналитика → Дизайн/Бэк/Фронт;
        # Дизайн → Фронт; Бэк/Фронт — все задачи уже в тестировании или
        # закрыты); оба = зелёный. Сценарий из completedScenarios — весь зелёный.
        def started(sid):
            j = jira.get(sid)
            return bool(j) and j["category"] != "backlog"
        def dev_passed(ts):
            return bool(ts) and all(t["category"] == "done" or
                                    (t.get("status") or "").strip().lower() in QA_STATUSES for t in ts)
        completed = r["code"] in completed_codes
        state = {}
        for sid in ("AN", "DS", "BE", "BE1", "BE2", "FE", "QA"):
            j = jira.get(sid)
            if completed or (j and j["category"] == "done"):
                state[sid] = "done"
            elif sid == "AN" and any(started(x) for x in ("DS", "BE", "FE")):
                state[sid] = "passed"
            elif sid == "DS" and started("FE"):
                state[sid] = "passed"
            elif sid in ("BE", "BE1", "BE2", "FE") and dev_passed(by[sid] or (by["BE"] if sid in ("BE1", "BE2") else [])):
                state[sid] = "passed"
            elif j and j["category"] == "in_progress":
                state[sid] = "active"
            else:
                state[sid] = "todo"
        planned = sorted(int(k) for k in r["cells"])
        first, last = (planned[0], planned[-1]) if planned else (None, None)
        used = {s for v in r["cells"].values() for s in v}
        # Зелёным этап может быть только в начавшихся спринтах: будущая работа
        # по плану ещё не заведена в Jira, «закрыто всё, что есть» ≠ сделано.
        all_green = bool(used) and last is not None and last <= cur_sprint and             all(state.get(s) in ("done", "passed") for s in used)
        # Стадия запуска для сортировки «по времени»: завершён / план прошёл,
        # а работа не закрыта / идёт сейчас по плану / впереди.
        phase = ("completed" if completed or all_green else
                 "next" if first is None or first > cur_sprint else
                 "overdue" if last < cur_sprint else "now")
        rows.append({**r, "jira": jira, "state": state, "completed": completed,
                     "firstSprint": first, "lastSprint": last, "phase": phase})
    return {"source": mp.get("source"), "sprints": mp.get("sprints"), "rows": rows,
            "completedWhy": completed_why}


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
BASELINE_FIELDS = ("key", "type", "parent", "epic", "role", "start", "planStart", "end",
                   "estimateH", "spentH", "status", "category", "resource",
                   "deps", "onCriticalPath")


def baseline_item(it, res_name):
    """Снимок одного элемента ганта для baselines[] (сравнение план/факт)."""
    b = {k: it[k] for k in BASELINE_FIELDS if it.get(k) not in (None, "", [])}
    b["summary"] = (it.get("summary") or "")[:90]
    if it.get("resource"):
        b["resourceName"] = res_name.get(it["resource"], it["resource"])
    return b


def baselines_path(data_path):
    """Слепки лежат отдельным файлом рядом с data.json: их читает только
    страница Ганта (по требованию), а data.json грузит каждая страница —
    со слепками всех уровней он раздувался 1.1 → 2 МБ (03.10.2026)."""
    return os.path.join(os.path.dirname(os.path.abspath(data_path)), "baselines.json")


def load_baselines(data_path, old):
    p = baselines_path(data_path)
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8")).get("baselines", [])
    # Миграция: до 03.10.2026 слепки с items лежали прямо в data.json.
    return old.get("baselines", [])


def run_gantt(args):
    now = datetime.now().astimezone()
    now_iso = now.replace(microsecond=0).isoformat()
    today = now.date()

    issues, total_issues = load_jira(args.jira)
    team = json.load(open(args.team, encoding="utf-8"))
    team = team.get("team", team) if isinstance(team, dict) else team
    old = json.load(open(args.data, encoding="utf-8"))

    # Вакантные ставки-гипотезы (FE-2/BE-1/QA-2 и т.п.) больше не показываем и
    # не назначаем на них задачи (Виктор 21.09.2026: считаем, что их не будет).
    resources = [r for r in build_resources(team, issues) if not r.get("vacant")]
    # Сценарий стори нужен ДО планирования: бэклог раскладывается по «Плану
    # ручному», а он задан по сценариям (26.10.2026).
    reg = load_scenarios(args.scenarios)
    manual = json.load(open(args.manual_plan, encoding="utf-8")) if args.manual_plan and os.path.exists(args.manual_plan) else None
    story_scenario = {}
    if reg:
        pre = [{"type": "story", "key": i["key"]} for i in issues if i["type"] == "story"]
        assign_scenarios(pre, issues, reg)
        story_scenario = {p["key"]: p["scenario"] for p in pre}
    items, end_date, crit_res, mvp_story_keys, orphan_report, sprint_load = plan_gantt(
        issues, resources, today, manual, story_scenario)

    # Сценарии и спринты (20.10.2026): привязка стори/задач к сценариям реестра,
    # агрегаты этапов и календарь спринтов для отсечек на ганте.
    scenarios = []
    if reg:
        assign_scenarios(items, issues, reg)
        scenarios = calc_scenarios(items, reg, today)
    raw_dump = json.load(open(args.jira, encoding="utf-8"))
    jira_sprints = raw_dump.get("sprints") if isinstance(raw_dump, dict) else None
    sprints = sprint_calendar(max(end_date or today, DEADLINE), today, jira_sprints)

    mvp_scope = calc_mvp_scope(items)
    resource_plan = calc_resource_plan(items, resources)
    # Загрузка по спринтам (часы / ёмкость 2 недели × 8ч × FTE) — для
    # страницы ресурсов; перегруз >100% = задач в спринте больше, чем влезает.
    for rp in resource_plan:
        rows = []
        for k, v in sprint_load.items():
            rid, n = k.split("|")
            if rid == rp["resourceId"]:
                rows.append({"n": int(n), "hours": v["hours"], "capacity": v["capacity"],
                             "loadPct": round(v["hours"] / v["capacity"] * 100) if v["capacity"] else None})
        rp["sprints"] = sorted(rows, key=lambda x: x["n"])
    manual_plan = calc_manual_plan(manual, items, resources, reg, sprint_index(today)) if manual else None
    # Страница «Статус для руководства» (дашборд Леонида, 26.10.2026): цели
    # спринтов со страницы «Реализация» + задачи прошлого и текущего спринта.
    cur_sp = sprint_index(today)
    goals = json.load(open(args.sprint_goals, encoding="utf-8")) if args.sprint_goals and os.path.exists(args.sprint_goals) else None
    status_page = {"currentSprint": cur_sp, "lastClosedSprint": cur_sp - 1,
                   "sprintGoals": goals,
                   "sprintStats": {str(n): calc_sprint_stats(items, reg, n) for n in (cur_sp - 1, cur_sp)}}
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
    crit_end_txt = end_date.strftime("%d.%m.%y") if end_date else "—"   # на сайте даты дд.мм.гг
    days_to_deadline = (DEADLINE - today).days

    # Счётчики по ВСЕМ задачам проекта (не MVP)
    story_st, task_st = calc_status_counters(issues)
    role_est = calc_role_estimates(issues)

    ganttV2 = {
        "generatedAt": now_iso,
        "workCalendar": {"holidays": sorted(HOLIDAYS), "hoursPerDay": HOURS_PER_DAY},
        "resources": resources,
        "items": items,
        "sprints": sprints,
        "scenarios": scenarios,
        "manualPlan": manual_plan,
        "statusPage": status_page,
        "mvpScope": mvp_scope,
        "criticalPathExplained": {
            "method": "Критический путь = цепочка задач до max(end) по ресурсу-хвосту.",
            "endDate": crit_end_iso,
            "resource": crit_res,
            "conclusion": (f"Успеваем к 10.12.26: критпуть до {crit_end_txt}" if end_date and end_date <= DEADLINE
                           else f"НЕ успеваем: критпуть до {crit_end_txt}, дедлайн 10.12.26"),
            "steps": [
                "Весь бэклог из выгрузки по 10 согласованным эпикам; вакантные ставки не учитываются вообще",
                "Спринтовая модель: задачи из спринтов Jira — в своём спринте (завершённые, в т.ч. Waiting for release, — в спринте завершения; Спринт 0 — по факту); внутри спринта задачи исполнителя идут подряд по часам",
                "Бэклог без спринта — в будущие спринты по «Плану ручному» (Confluence 2666206915; Бек 1 = Попов, Бек 2 = Григоркин) с учётом ёмкости 2 недели × 8ч × FTE; не влезло — в следующий спринт",
                "Зависимости ролей внутри стори — по спринтам: BA → (ARC) → DS и BE → FE не раньше DS и BE → QA; + явные Blocks",
                f"Хвост критпути: ресурс {crit_res}, окончание {crit_end_txt}",
            ],
        },
        "ganttAssumptions": {
            "dataSource": f"Jira B2BAPP {now_iso} (динамически)",
            "teamSource": "Confluence 1562745210 + сверка Jira assignee",
            "ganttType": "per_task_v4_sprints",
            "calendar": "Производственный календарь РФ",
            "excludedFromGantt": "Вакантные ставки (FE-2/BE-1/QA-2 и т.п.) — считаем, что их не будет, задачи на них не назначаются",
            "excludedScenarios": [
                {"code": "OB10", "group": "Обращения и клиенты", "name": "Напоминания (авто из звонка + вручную)",
                 "reason": "нет оценки"},
                {"code": "PL1", "group": "Платформа/Ядро", "name": "Единый ИИ-движок и модель взаимодействия",
                 "reason": "отдельной задачи нет — неотъемлемая часть любого процесса, где будем переиспользовать"},
                {"code": "PL4", "group": "Платформа/Ядро", "name": "Сценарии-редиректы + замоканные",
                 "reason": "оценка не требуется, будет реализовываться по ходу проекта и отдельных сценариев"},
                {"code": "PL5", "group": "Платформа/Ядро", "name": "ИИ-гигиена (запретные темы, tone of voice, лимиты)",
                 "reason": "оценка не требуется, будет реализовываться по ходу проекта и отдельных сценариев"},
                {"code": "PL7", "group": "Платформа/Ядро", "name": "Продуктовая аналитика",
                 "reason": "нет оценки — нет понимания, по каким продуктам и какие метрики нужны"},
                {"code": "PL11", "group": "Платформа/Ядро", "name": "Бесшовная аутентификация",
                 "reason": "не может быть выполнена сейчас — начнётся после первичной/B2C-архитектуры"},
                {"code": "PL16", "group": "Платформа/Ядро", "name": "Управление настройками в Профиле",
                 "reason": "не оценивали"},
                {"code": "PL17", "group": "Платформа/Ядро", "name": "Отправка пуш-уведомлений",
                 "reason": "не оценивали"},
                {"code": "PL18", "group": "Платформа/Ядро", "name": "Анализ запросов и самоулучшение",
                 "reason": "не оценивали"},
                {"code": "IB", "group": "Трек с ИБ", "name": "Выход в продуктив",
                 "reason": "большой трек, невозможно оценить целиком — переиспользуем функционал, "
                           "нужно отдельно по каждому пункту решать с ИБ"},
            ],
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
    bl = [b for b in load_baselines(args.data, old) if b.get("id") != bl_id]
    res_name = {r["id"]: r.get("name") or r["id"] for r in resources}
    bl.append({
        "id": bl_id,
        "ts": now_iso,
        "label": f"Refresh {today.strftime('%d.%m.%Y')} (MVP-only)",
        "criticalEnd": crit_end_iso,
        "criticalResource": crit_res,
        "hoursTotal": hours_total, "hoursSpent": hours_spent,
        # Все уровни + оценка/списание/статус/исполнитель: без них страница
        # Ганта может показать только «сдвинулось», но не «почему» (сравнение
        # слепков, запрос Виктора 03.10.2026). Раньше тут были только задачи
        # с start/end — у стори/эпиков на свёрнутом ганте сравнивать было нечего.
        "items": [baseline_item(it, res_name) for it in items],
    })
    new["baselines"] = [{k: v for k, v in b.items() if k != "items"} | {"nItems": len(b.get("items") or [])}
                        for b in bl]

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

    # Сироты — задачи без Part-связи на стори в Jira (или связанные со стори
    # вне 10 согласованных эпиков), запланированы напрямую под эпик как
    # fallback. Список — чтобы можно было проставить Part-связи в Jira и
    # больше в нём не нуждаться.
    new["orphanTasks"] = orphan_report

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
    bl_out = baselines_path(args.out)
    json.dump({"baselines": bl}, open(bl_out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"OK. Записан {args.out} (+ {bl_out}, слепков: {len(bl)})")
    print(f"  MVP: {len(mvp_epics)} эпиков, {len(mvp_stories)} стори, {len(mvp_tasks_it)} задач")
    print(f"  Часы: {hours_total} план / {hours_spent} списано ({completion}%)")
    print(f"  Критпуть до {crit_end_iso} (ресурс {crit_res}), "
          f"{'успеваем' if new['kpi']['mvpReachable'] else 'НЕ успеваем'} к 10.12.2026")
    print(f"  Ресурсов: {len(resources)} (реальных {sum(1 for r in resources if not r['vacant'])}, "
          f"вакансий {sum(1 for r in resources if r['vacant'])})")
    print(f"  scopeGrowth точек: {len(sg)}, baselines: {len(bl)}")
    act = next((s for s in sprints if s["state"] == "active"), None)
    print(f"  Спринтов в календаре: {len(sprints)}; текущий: {act['name'] + ' ' + act['start'] + '–' + act['end'] if act else '—'}")
    if scenarios:
        by_src = Counter((it.get("scenarioSource") or "").split(":")[0] for it in items if it["type"] == "story")
        print(f"  Сценариев: {len(scenarios)} (с задачами {sum(1 for s in scenarios if s['tasks'])}); "
              f"привязка стори: {dict(by_src)}")
        miss = Counter(m for s in scenarios if s["tasks"] for m in s.get("missingStages", []))
        if miss:
            print(f"  ⚠ Сценариев без задач обязательного этапа (из {sum(1 for s in scenarios if s['tasks'])}): "
                  f"{dict(miss)} — в Jira нет задач [BA]/[ARC], [BE] или [QA]")
    if orphan_report:
        orphan_h = sum(o["estimateH"] for o in orphan_report)
        print(f"  ⚠ Задач-сирот (без Part-связи на стори, запланированы напрямую под эпик): "
              f"{len(orphan_report)}, {orphan_h}ч — {', '.join(o['key'] for o in orphan_report)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["gantt", "registries", "usm"])
    ap.add_argument("--jira")
    ap.add_argument("--team")
    ap.add_argument("--confluence")
    ap.add_argument("--scenarios", default="scenarios.json",
                    help="реестр сценариев (Confluence 2356754448) + привязки стори")
    ap.add_argument("--manual-plan", default="manual_plan.json",
                    help="«План ручной» (Confluence 2666206915), см. parse_manual_plan.py")
    ap.add_argument("--sprint-goals", default="sprint_goals.json",
                    help="цели спринтов (Confluence 1562746234), см. parse_sprint_goals.py")
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
