"""Аудит задач по аналитикам → public/data/audit.json (страница pages/audit.html).

Спецификация — Cowork, 11.11.2026 («Spec audit page for dashboard»): правки
оформления Jira (S4–S6, T1–T12) по ответственным аналитикам + этапы сценариев,
отстающие от «Плана ручного» (P4). Страница только рисует этот JSON.

P4 берётся из уже посчитанного дашборда (data.json → ganttV2.manualPlan), по
тому же правилу, что штриховка на виде «Этапы по сценариям», — число находок
P4 совпадает с числом заштрихованных этапов. К каждой незакрытой задаче этапа
добавлено, стоит ли она в текущем/будущем спринте Jira (Виктор 11.11.2026:
этап в прошлом → его задачи должны быть закрыты либо запланированы вперёд).

Проверки оформления — по всему проекту (jira_full_dump.json: эпики, стори,
задачи всех эпиков, без вакантных).

    python build_audit.py --jira-full jira_full_dump.json --data public/data/data.json \
        --registry cf/cf_registry_ДДММ.json --out public/data/audit.json
"""
import argparse
import glob
import json
import os
import re
from datetime import date

T_EPIC, T_STORY, T_TASK, T_DEV = "10500", "10600", "3", "20600"
CLOSED = {"завершена", "отклонена", "waiting for release", "ready for release"}
SERVICE_STORIES = {"B2BAPP-2", "B2BAPP-4", "B2BAPP-7", "B2BAPP-8", "B2BAPP-55", "B2BAPP-193", "B2BAPP-12"}
EXEMPT_EPIC = "B2BAPP-1"
ROLE_RE = re.compile(r"^\s*(?:\d+[.:]\s*)?\[([A-Za-zА-Яа-я]+)\]")
ROLES = {"BA", "ARC", "DS", "BE", "FE", "QA", "DVO", "ORG"}
SC_LABEL_RE = re.compile(r"^(MD|OB|RB|PL|PK|NAI|B2C|YD|IB|SH)\d*$", re.I)
SC_PREFIX_RE = re.compile(r"^\s*((?:MD|OB|RB|PL|PK|NAI|B2C|YD|IB|SH)\d*)\s*[.:]", re.I)
# Вне MVP (Виктор 12.11.2026): договоры/счета/платежи — метка сценария SH, всё дерево
# эпика B2BAPP-23 — метка «вне_MVP»; такие задачи и задачи эпиков вне 10 MVP-эпиков
# аудит не проверяет совсем.
OUT_LABEL, OUT_SCENARIO = "вне_MVP", "SH"
VACANT_EPIC = "B2BAPP-135"
STAGE_NAME = {"AN": "Аналитика", "DS": "Дизайн", "BE": "Бек", "BE1": "Бек", "BE2": "Бек", "FE": "Фронт", "QA": "QA"}
STAGE_ROLES = {"AN": "[BA]/[ARC]", "DS": "[DS]", "BE": "[BE]", "BE1": "[BE]", "BE2": "[BE]", "FE": "[FE]", "QA": "[FE]/[BE]/[QA]"}
# Ответственный за сценарий — колонка «Владелец» реестра MVP v.2. С 12.11.2026 там один
# человек на сценарий, упоминанием @пользователь (не обязательно аналитик: PL5 — Алпатов).
# Без сценария или вне реестра — РП (на разбор).
FALLBACK = "Немудров Виктор"
SHORT = {"Клейменова Анна": "Аня", "Шевченко Константин": "Костя", "Немудров Виктор": "Виктор"}
# Задача длиннее 2 рабочих дней — разбить (Виктор 12.11.2026). Синхрон с аналитиками
# 12.11.2026: только ещё не взятые в работу — «Бэклог» и «Ready for DEV» (Виктор 13.11.2026:
# в остальных статусах проверка не нужна).
MAX_TASK_H = 16
SPLIT_STATUSES = {"бэклог", "backlog", "ready for dev"}
# Стори, где разработка не требуется — S6 не проверяем (Виктор 13.11.2026).
NO_DEV_STORIES = {"B2BAPP-924", "B2BAPP-1188"}
DONE_REG = re.compile(r"^\s*(готово|реализовано)", re.I)
GLOSSARY = [
    ("S4", "стори без привязки к эпику (Epic Link)"),
    ("S5", "у стори нет метки сценария — определить и проставить"),
    ("S6", "в стори только аналитик [BA], нет задач разработки"),
    ("T1", "у задачи нет префикса роли ([BE]/[FE]/[BA]…)"),
    ("T3", "тип задачи не совпадает с ролью в префиксе"),
    ("T4", "у задачи нет Part-связи со стори"),
    ("T6", "у задачи нет оценки"),
    ("T7", f"оценка больше {MAX_TASK_H} ч (2 рабочих дня) — разбить на задачи меньше; только в статусах "
           "«Бэклог» и «Ready for DEV»"),
    ("T13", "задача лежит в вакантной стори/эпике, но по ней работают (списано время или статус не «Бэклог») — "
            "привязать к рабочей стори и эпику"),
    ("V1", "в вакантные переведена задача/стори, по которой уже списано время или которая была закрыта "
           "(Завершена / Waiting for release / Ready for release) — так нельзя: вернуть прежние данные по истории "
           "изменений; вакантить можно только не начатое и без списаний"),
    ("T11", "задача начата, но без даты начала"),
    ("T12", "задача закрыта без даты решения"),
    ("SC1", "в реестре MVP v.2 сценарий отмечен «Готово/Реализовано», а в Jira есть незакрытые задачи — "
            "поправить статус в реестре (Confluence) или закрыть задачи"),
    ("SC2", "все задачи сценария закрыты, а стори нет — закрыть стори (Waiting for release): по закрытым стори "
            "сценарий красится зелёным на «Статусе для руководства»"),
    ("SC3", "стори сценария закрыты, а задачи — нет: закрыть задачи или вернуть стори в работу"),
    ("P4", "этап сценария отстаёт от «Плана ручного»: последний спринт этапа прошёл, а в Jira он не закрыт — "
           "задачи надо закрыть или запланировать в будущий спринт (заштрихован на «Этапах по сценариям»)"),
]


def person(cell, team):
    """«Фамилия Имя» первого человека в ячейке «Владелец». Упоминания в выгрузке уже
    заменены на ФИО; старый текстовый формат («Шевченок/Самойло») сопоставляется с
    командой по первым 3 буквам фамилии (в реестре бывают опечатки)."""
    first = re.split(r"\s*[/(,+]\s*", (cell or "").strip())[0].strip()
    if not first:
        return None
    words = first.split()
    if len(words) >= 2:
        return " ".join(words[:2])
    key = words[0][:3].lower()
    for full in team:
        if full.lower().startswith(key):
            return full
    return words[0]


def load_owner_map(path, team):
    reg = json.load(open(path, encoding="utf-8"))
    m = {}
    for t in reg.get("tables", []):
        if not t or "Владелец" not in t[0] or "№" not in t[0]:
            continue
        ci, co = t[0].index("№"), t[0].index("Владелец")
        for r in t[1:]:
            if len(r) > max(ci, co) and r[ci].strip():
                who = person(r[co], team)
                if who:
                    m[r[ci].strip().upper()] = who
    return m


def load_reg_status(path):
    """Колонка «Статус» реестра MVP v.2: код сценария → текст статуса."""
    reg = json.load(open(path, encoding="utf-8"))
    m = {}
    for t in reg.get("tables", []):
        if t and "Статус" in t[0] and "№" in t[0]:
            ci, cs = t[0].index("№"), t[0].index("Статус")
            for r in t[1:]:
                if len(r) > max(ci, cs) and r[ci].strip():
                    m[r[ci].strip().upper()] = r[cs].strip()
    return m


def scenario_of(story):
    for lb in story.get("labels") or []:
        if SC_LABEL_RE.match(lb):
            return lb.upper()
    m = SC_PREFIX_RE.match(story.get("summary") or "")
    return m.group(1).upper() if m else None


def role_of(summary):
    m = ROLE_RE.match(summary or "")
    r = m.group(1).upper() if m else None
    return r if r in ROLES else None


def sprint_label(sprints):
    """Самый поздний открытый (активный/будущий) спринт задачи в Jira или None."""
    best = None
    for s in sprints or []:
        st = (s.get("state") or "").upper()
        if st in ("ACTIVE", "FUTURE"):
            m = re.search(r"Спринт\s*(\d+)", s.get("name") or "")
            n = int(m.group(1)) if m else None
            if best is None or (n or 0) > (best[0] or 0):
                best = (n, st)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jira-full", default="jira_full_dump.json")
    ap.add_argument("--data", default="public/data/data.json")
    ap.add_argument("--registry", default=None, help="выгрузка реестра MVP v.2 (cf/cf_registry_*.json), по умолчанию самая свежая")
    ap.add_argument("--out", default="public/data/audit.json")
    a = ap.parse_args()
    reg_path = a.registry or max(glob.glob("cf/cf_registry_*.json"), key=os.path.getmtime)
    full = json.load(open(a.jira_full, encoding="utf-8"))
    data = json.load(open(a.data, encoding="utf-8"))
    team = [" ".join(m["name"].split()[:2]) for m in (data.get("teamConfluence") or {}).get("members", [])
            if m.get("status") != "vacant"]
    own = load_owner_map(reg_path, team)
    gv = data.get("ganttV2") or {}
    today = date.today().isoformat()

    iss = [i for i in full["issues"] if "акантн" not in (i.get("summary") or "")]
    vacant = {i["key"] for i in full["issues"] if "акантн" in (i.get("summary") or "")}
    by_key = {i["key"]: i for i in iss}
    stories = [i for i in iss if i["type"] == T_STORY]
    tasks = [i for i in iss if i["type"] in (T_TASK, T_DEV)]
    epics = [i for i in iss if i["type"] == T_EPIC]

    def parent_stories(t):
        return [l["in"] for l in t.get("links") or []
                if l["type"] == "Part" and l.get("in") and l.get("inType") == T_STORY and l["in"] in by_key]

    def parent_story(t):
        ps = parent_stories(t)
        return ps[0] if ps else None

    def in_vacant(t):
        return t.get("epic") == VACANT_EPIC or any(
            l["type"] == "Part" and l.get("in") in vacant for l in t.get("links") or [])

    sc = {s["key"]: scenario_of(s) for s in stories}
    story_tasks = {}
    for t in tasks:
        for p in parent_stories(t):      # одна задача на несколько стори — во всех
            story_tasks.setdefault(p, []).append(t)

    owners = {}

    def owner(name):
        name = name or FALLBACK
        if name not in owners:
            owners[name] = {"id": f"o{len(owners) + 1}", "name": name, "short": SHORT.get(name, name.split()[-1]),
                            "fallback": name == FALLBACK, "scenarios": [], "issues": [], "p4": [], "unlabeled_stories": [],
                            "scenario_checks": []}
        return owners[name]

    for code, name in own.items():
        owner(name)["scenarios"].append(code)
    owner(FALLBACK)

    mvp_epics = {e["epicKey"] for e in data.get("epicProgress") or []}
    excluded = {"stories": 0, "tasks": 0}

    def out_of_mvp(i, story=None):
        """Вне MVP — не проверяем: метка «вне_MVP» (у задачи или её стори), сценарий SH,
        эпик вне 10 MVP-эпиков. Без эпика, вакантный эпик и B2BAPP-1 — проверяем."""
        if OUT_LABEL in (i.get("labels") or []) or (story and OUT_LABEL in (story.get("labels") or [])):
            return True
        if story and sc.get(story["key"]) == OUT_SCENARIO or sc.get(i["key"]) == OUT_SCENARIO:
            return True
        ep = i.get("epic") or (story or {}).get("epic")
        return bool(mvp_epics) and ep and ep not in mvp_epics and ep not in (EXEMPT_EPIC, VACANT_EPIC)

    # Кто разбирает находку (Виктор 12.11.2026): владелец сценария по реестру; если сценарий
    # за РП или его нет — аналитик-исполнитель задачи, иначе аналитик, который последним
    # отправил её в вакантные (vacatedBy) или последним менял привязку (linkedBy из выгрузки),
    # иначе исполнитель стори; иначе — РП.
    analysts = {n for n in own.values() if n != FALLBACK}

    def resp(scen, *cands):
        o = own.get(scen) if scen else None
        if o and o != FALLBACK:
            return o
        for c in cands:
            c = " ".join((c or "").split()[:2])
            if c in analysts:
                return c
        return o or FALLBACK

    def add(oname, key, scen, check, action):
        it = {"key": key, "scenario": scen or "—", "check": check, "action": action}
        owner(oname)["issues"].append(it)

    # ── Стори ──
    for s in stories:
        k = s["key"]
        if k in SERVICE_STORIES:
            continue
        if out_of_mvp(s):
            excluded["stories"] += 1
            continue
        scen = sc[k]
        kid_assignees = sorted((t.get("assignee") for t in story_tasks.get(k, []) if t.get("assignee")),
                               key=lambda a: -sum(1 for t in story_tasks.get(k, []) if t.get("assignee") == a))
        oid = resp(scen, s.get("assignee"), *kid_assignees)
        checks, acts = [], []
        if not s.get("epic"):
            checks.append("S4"); acts.append("привязать к эпику (Epic Link)")
        if not scen and s.get("epic") != EXEMPT_EPIC:
            # вопрос — исполнителю стори, не РП (Виктор 12.11.2026)
            owner(oid)["unlabeled_stories"].append(k)
        roles = {role_of(t["summary"]) for t in story_tasks.get(k, [])}
        if roles and roles <= {"BA"} and k not in NO_DEV_STORIES:
            checks.append("S6"); acts.append("только [BA] — добавить задачи разработки")
        if checks:
            if not scen and s.get("epic") != EXEMPT_EPIC:
                checks.insert(0, "S5"); acts.insert(0, "нет метки сценария")
            add(oid, k, scen, ", ".join(checks), "; ".join(acts))

    # ── Задачи ──
    for t in tasks:
        k, st = t["key"], (t.get("status") or "").strip()
        p = parent_story(t)
        if out_of_mvp(t, by_key.get(p)):
            excluded["tasks"] += 1
            continue
        scen = sc.get(p) if p else None
        oid = resp(scen, t.get("assignee"), t.get("vacatedBy"), t.get("linkedBy"), (by_key.get(p) or {}).get("assignee"))
        exempt = t.get("epic") == EXEMPT_EPIC or (p and by_key[p].get("epic") == EXEMPT_EPIC)
        role = role_of(t["summary"])
        checks, acts = [], []
        if not role and not exempt:
            checks.append("T1"); acts.append("добавить префикс роли")
        if role:
            want = T_DEV if role in ("BE", "FE") else T_TASK
            if t["type"] != want:
                checks.append("T3"); acts.append(f"тип [{role}] → {'Development' if want == T_DEV else 'Задача'}")
        if in_vacant(t) and (t.get("spent") or st.lower() not in ("бэклог", "backlog")):
            checks.append("T13"); acts.append(f"в вакантной, а списано {round((t.get('spent') or 0) / 3600, 1)} ч / статус «{st}» — "
                                              "привязать к рабочей стори и эпику")
        elif not p:
            checks.append("T4"); acts.append("привязать Part к стори")
        if not t.get("est") and st.lower() not in CLOSED:
            checks.append("T6"); acts.append("проставить оценку")
        if t.get("est", 0) > MAX_TASK_H * 3600 and st.lower() in SPLIT_STATUSES:
            checks.append("T7"); acts.append(f"оценка {round(t['est'] / 3600)} ч > {MAX_TASK_H} ч — разбить на задачи до 2 дней")
        if st.lower() != "бэклог" and not t.get("start"):
            checks.append("T11"); acts.append("проставить «Дату начала»")
        if st.lower() == "завершена" and not t.get("resolved"):
            checks.append("T12"); acts.append("закрыта без даты решения — переоткрыть и закрыть заново")
        if checks:
            add(oid, k, scen, ", ".join(checks), "; ".join(acts))

    # ── V1: неправильно завакантили (Виктор 13.11.2026) — находка тому, кто перевёл в вакантные ──
    for t in full["issues"]:
        if not t.get("vacantBad"):
            continue
        who = " ".join((t.get("vacatedBy") or "").split()[:2])
        why = []
        if t.get("spent"):
            why.append(f"списано {round(t['spent'] / 3600, 1)} ч")
        if (t.get("statusBeforeVacant") or "").strip().lower() in CLOSED | {"done"}:
            why.append(f"была в статусе «{t['statusBeforeVacant']}»")
        elif t.get("statusBeforeVacant") and t["statusBeforeVacant"].strip().lower() not in ("бэклог", "backlog"):
            why.append(f"была в работе («{t['statusBeforeVacant']}»)")
        va = t.get("vacatedAt") or ""
        va = f"{va[8:10]}.{va[5:7]}.{va[2:4]}" if len(va) == 10 else va
        m = SC_PREFIX_RE.match(t.get("vacatedFrom") or "")
        add(who if who in analysts else FALLBACK, t["key"], m.group(1).upper() if m else "—", "V1",
            f"переведена в вакантные {va} ({who or 'автор не найден'}): {', '.join(why) or 'закрывалась'} — "
            f"вернуть «{(t.get('vacatedFrom') or '')[:60]}», эпик, связи и статус по истории изменений")

    # ── Сценарии: отметка о завершении и закрытие стори (синхрон 12.11.2026) ──
    reg_status = load_reg_status(reg_path)
    for code in sorted(set(own) | set(reg_status)):
        ss = [x for x in stories if sc.get(x["key"]) == code and x["key"] not in SERVICE_STORIES and not out_of_mvp(x)]
        ts = {t["key"]: t for x in ss for t in story_tasks.get(x["key"], [])}
        if not ss:
            continue
        open_t = sorted((k for k, t in ts.items() if (t.get("status") or "").strip().lower() not in CLOSED),
                        key=lambda k: int(k.split("-")[1]))
        open_s = sorted((x["key"] for x in ss if (x.get("status") or "").strip().lower() not in CLOSED),
                        key=lambda k: int(k.split("-")[1]))
        o = owner(own.get(code, FALLBACK))
        if DONE_REG.match(reg_status.get(code) or "") and (open_t or open_s):
            o["scenario_checks"].append({"scenario": code, "check": "SC1", "keys": open_t or open_s,
                "action": f"в реестре «{reg_status[code][:40]}», а в Jira незакрыто: задач {len(open_t)}, стори {len(open_s)} — "
                          "поправить статус в реестре или закрыть задачи"})
        if ts and not open_t and open_s:
            o["scenario_checks"].append({"scenario": code, "check": "SC2", "keys": open_s,
                "action": "все задачи закрыты — закрыть стори (Waiting for release), если трек завершён"})
        if open_t and not open_s:
            o["scenario_checks"].append({"scenario": code, "check": "SC3", "keys": open_t,
                "action": f"все стори закрыты, а {len(open_t)} задач открыто — закрыть задачи или вернуть стори в работу"})

    # ── P4: отстающие этапы — по данным дашборда (то же правило, что штриховка) ──
    mp = gv.get("manualPlan") or {}
    sp_end = {s["n"]: s.get("end") for s in (mp.get("sprints") or [])}
    for s in gv.get("sprints") or []:
        sp_end[s["n"]] = s.get("end")
    cur = next((s["n"] for s in sorted(gv.get("sprints") or [], key=lambda s: s["n"])
                if (s.get("start") or "") <= today <= (s.get("end") or "")), None) or \
        ((gv.get("statusPage") or {}).get("currentSprint") or 0)
    n_p4 = 0
    for r in mp.get("rows") or []:
        if r.get("completed"):
            continue
        cells = {int(n): v for n, v in (r.get("cells") or {}).items()}
        state, jira = r.get("state") or {}, r.get("jira") or {}
        seen = set()
        for sid in ("AN", "DS", "BE", "BE1", "BE2", "FE", "QA"):
            ns = sorted(n for n, v in cells.items() if sid in v)
            runs, cur_run = [], []
            for n in ns:
                if cur_run and n != cur_run[-1] + 1:
                    runs.append(cur_run); cur_run = []
                cur_run.append(n)
            if cur_run:
                runs.append(cur_run)
            for run in runs:
                end = sp_end.get(run[-1])
                green = run[-1] <= (cur or 99) and state.get(sid) in ("done", "passed")
                if green or not end or end > today:
                    continue
                stage = STAGE_NAME[sid]
                dkey = (stage, run[0], run[-1])
                if dkey in seen:          # Бек 1 и Бек 2 в плане — одна проверка по всем [BE]
                    continue
                seen.add(dkey)
                j = jira.get(sid) or (jira.get("BE") if sid in ("BE1", "BE2") else None) or {}
                lst = j.get("list") or []
                open_t = [x for x in lst if x["s"].strip().lower() not in CLOSED]
                rows = []
                for x in open_t:
                    spn = sprint_label((by_key.get(x["k"]) or {}).get("sprints"))
                    plan = (f"в Спринте {spn[0]}" + (" (текущий)" if spn[1] == "ACTIVE" else " (будущий)")) if spn else None
                    rows.append({"key": x["k"], "status": x["s"], "summary": x["t"], "sprint": plan})
                in_sprint = sum(1 for x in rows if x["sprint"])
                if not lst:
                    kind, action = "нет", f"завести задачи {STAGE_ROLES[sid]} или убрать этап из «Плана ручного»"
                elif in_sprint == len(rows):
                    kind, action = "открыт", "задачи запланированы в спринт — перенести этап в «Плане ручном» на этот спринт"
                else:
                    kind, action = "открыт", "задачи без спринта: закрыть или запланировать в будущий спринт"
                owner(own.get(r["code"].upper(), FALLBACK))["p4"].append({
                    "scenario": r["code"], "name": r.get("name"), "stage": stage,
                    "plan": "Спринт " + ",".join(str(n) for n in run),
                    "planEnd": end, "kind": kind, "jira": rows,
                    "closed": len(lst) - len(open_t), "total": len(lst), "action": action})
                n_p4 += 1

    for o in owners.values():
        o["scenarios"].sort(key=lambda c: (re.sub(r"\d+", "", c), int(re.sub(r"\D", "", c) or 0)))
        o["issues"].sort(key=lambda x: (x["check"], int(x["key"].split("-")[1])))
        o["unlabeled_stories"].sort(key=lambda k: int(k.split("-")[1]))

    out = {
        "generated_at": today,
        "jira_collected_at": (full.get("collectedAt") or "")[:10],
        "current_sprint": cur,
        "scope": {"stories": len(stories) - excluded["stories"], "tasks": len(tasks) - excluded["tasks"], "epics": len(epics),
                  "excluded_stories": excluded["stories"], "excluded_tasks": excluded["tasks"]},
        "sprint_calendar": {str(n): e for n, e in sorted(sp_end.items())},
        "registry": os.path.basename(reg_path),
        "manual_plan": (mp.get("source") or {}),
        "glossary": [{"code": c, "text": t} for c, t in GLOSSARY],
        # РП («на разбор») — последним; остальные — по числу сценариев
        "owners": sorted(owners.values(), key=lambda o: (o["fallback"], -len(o["scenarios"]), o["name"])),
        "deadline_note": "правки в Jira и Confluence — до конца пятницы (МСК): срез дашборда снимается вечером пятницы",
        "max_task_h": MAX_TASK_H,
        "p4_total": n_p4,
    }
    json.dump(out, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"OK {a.out}: стори {len(stories)}, задач {len(tasks)}, эпиков {len(epics)}; "
          + "; ".join(f"{o['short']}: {len(o['issues'])} правок, P4 {len(o['p4'])}" for o in out["owners"])
          + f"; без метки {sum(len(o['unlabeled_stories']) for o in owners.values())}; P4 всего {n_p4}; "
          + f"вне MVP пропущено стори {excluded['stories']}, задач {excluded['tasks']} (реестр {out['registry']})")


if __name__ == "__main__":
    main()
