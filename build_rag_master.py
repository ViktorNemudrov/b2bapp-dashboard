# -*- coding: utf-8 -*-
"""Мастер-файл плана работ B2BAPP для RAG (Claude Project).

Запрос Виктора 11.10.2026: план работ используется во многих отчётах, и чат не
должен каждый раз ходить в Jira и пересчитывать — после каждого обновления
дашборда формируется один самодостаточный файл со всеми данными плана.

Источник — уже посчитанный public/data/data.json (+ baselines.json для анализа
сдвигов через rag_compare.js, та же логика, что на странице Ганта). Ничего не
пересчитывает, только раскладывает в текст, удобный для поиска по чанкам:
каждый раздел начинается с шапки «B2BAPP · план на ДД.ММ.ГГГГ», у каждой задачи
одной строкой — эпик, стори, роль, исполнитель, статус, часы, даты, сдвиг.

python build_rag_master.py [--data public/data/data.json] [--out rag/MASTER_11_план_работ.md] [--copy-to DIR ...]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import date

DEADLINE = "2026-12-10"
ROLE_TITLE = {"ORG": "руководитель проекта", "ARC": "архитектор", "BA": "аналитик", "DS": "дизайнер",
              "BE": "бэкенд", "FE": "фронтенд", "QA": "тестирование", "DVO": "DevOps", "OTHER": "роль не определена"}
CAT_RU = {"done": "готово", "in_progress": "в работе", "backlog": "не начато"}
TEAM_ST = {"active": "в проекте, в расчёте ганта", "left": "ушёл из проекта", "vacant": "вакансия, не закрыта",
           "noplan": "в проекте, в гант как исполнитель не включён"}


def ddmmyy(s):
    return f"{s[8:10]}.{s[5:7]}.{s[0:4]}" if s else "—"


def h(x):
    x = round(x or 0, 1)
    return str(int(x)) if x == int(x) else str(x)


def shift_txt(n):
    if n is None:
        return "—"
    return f"+{n} раб. дн." if n > 0 else f"−{-n} раб. дн." if n < 0 else "без сдвига"


def two(n):
    return " ".join((n or "").split()[:2])


def cell(s):
    return str(s if s is not None else "").replace("|", "/").replace("\n", " ").strip()


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def remaining(t):
    if t["category"] == "done":
        return 0
    if t["category"] == "in_progress":
        return max((t.get("estimateH") or 0) - (t.get("spentH") or 0), 0)
    return t.get("estimateH") or 0


def previous_baseline(d, gen_day):
    """Последний содержательный слепок, снятый ДО текущего прогона."""
    cands = [b for b in d.get("baselines", []) if (b.get("nItems") or 0) > 0 and (b.get("ts") or "")[:10] < gen_day]
    return cands[-1] if cands else None


def run_compare(repo, data_path, bl):
    bl_path = os.path.join(os.path.dirname(data_path), "baselines.json")
    if not bl or not os.path.exists(bl_path):
        return None
    try:
        r = subprocess.run(["node", os.path.join(repo, "rag_compare.js"), data_path, bl_path, bl["ts"]],
                           capture_output=True, timeout=120)
        if r.returncode != 0:
            print("rag_compare.js:", r.stderr.decode("utf-8", "replace")[:500], file=sys.stderr)
            return None
        return json.loads(r.stdout.decode("utf-8"))
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        print("rag_compare.js не отработал:", e, file=sys.stderr)
        return None


def build(d, cmp):
    g = d["ganttV2"]
    items = g["items"]
    kpi = d.get("kpi", {})
    gen = (g.get("generatedAt") or d.get("refreshedAt") or "")[:10]
    asof = ddmmyy(gen)
    H = f"B2BAPP · план работ на {asof}"
    res_name = {r["id"]: r["name"] for r in g.get("resources", [])}
    epics = sorted([i for i in items if i["type"] == "epic"], key=lambda e: (e.get("priority") or 99, e["key"]))
    stories = [i for i in items if i["type"] == "story"]
    tasks = [i for i in items if i["type"] == "task"]
    st_by_epic = defaultdict(list)
    for s in stories:
        st_by_epic[s["epic"]].append(s)
    t_by_story = defaultdict(list)
    for t in tasks:
        t_by_story[t.get("parent") or ("E:" + t["epic"])].append(t)
    epic_name = {e["key"]: e["summary"] for e in epics}
    story_name = {s["key"]: s["summary"] for s in stories}
    crit_keys = {i["key"] for i in items if i.get("onCriticalPath")}
    mvp_in = {s["key"]: s for s in (g.get("mvpScope") or {}).get("inStories", [])}
    shift = {}
    if cmp:
        shift = {r["key"]: r for r in cmp["items"]}

    out = []
    w = out.append
    w(f"# MASTER_11 — План работ и диаграмма Ганта B2BAPP (данные на {asof})\n")
    w("Проект B2BAPP — мобильное приложение / ЛК для микробизнеса Билайн с AI-ассистентом. "
      "Этот файл — полный снимок плана работ, который формирует дашборд b2bapp-dashboard при каждом "
      "обновлении из Jira (btask.beeline.ru, проект B2BAPP, 10 согласованных MVP-эпиков) и Confluence "
      "(страница 1562745210 «Команда проекта»). Используй его как источник для отчётов, статусов и ответов "
      "по срокам, объёмам, загрузке и составу работ — в Jira за этими данными ходить не нужно. "
      f"Актуальность: Jira на {d.get('refreshedAt', gen)}. Файл перегенерируется целиком при каждом "
      "обновлении дашборда (примерно раз в неделю–месяц); более старые версии считать устаревшими.\n")
    w("Как читать: «раб. дн.» — рабочие дни по производственному календарю РФ, 8 ч в день; «ч» — часы оценки "
      "(Original Estimate) и списания (Time Spent) из Jira; «критпуть» — цепочка задач, определяющая дату "
      "окончания всего плана; «слепок» — сохранённая версия плана с прошлого обновления, с ней сравниваются сдвиги.\n")

    # 1. Ключевые цифры
    s = d.get("summary", {})
    w(f"## 1. Ключевые цифры ({H})\n")
    reach = "да" if kpi.get("mvpReachable") else "нет"
    w(table(["Показатель", "Значение"], [
        ["Дата данных", asof],
        ["Эпиков / стори / задач в плане", f"{kpi.get('totalEpics')} / {kpi.get('totalStories')} / {kpi.get('totalTasks')}"],
        ["Стори готово", f"{s.get('storiesDone')} из {s.get('stories')}"],
        ["Задач готово / в работе / не начато",
         f"{sum(t['category']=='done' for t in tasks)} / {sum(t['category']=='in_progress' for t in tasks)} / {sum(t['category']=='backlog' for t in tasks)}"],
        ["Объём плана, ч", h(kpi.get("hoursTotal"))],
        ["Списано, ч", h(kpi.get("hoursSpent"))],
        ["Остаток работы, ч", h(sum(remaining(t) for t in tasks))],
        ["Выполнение по часам", f"{kpi.get('completionPct')}%"],
        ["Дедлайн MVP", ddmmyy(DEADLINE)],
        ["Рабочих дней до дедлайна", kpi.get("daysToDeadline")],
        ["Расчётное окончание плана (критпуть)", ddmmyy(kpi.get("criticalEnd"))],
        ["Успеваем к дедлайну", reach],
        ["Ресурс-хвост критпути", f"{g['criticalPathExplained'].get('resource')} — {res_name.get(g['criticalPathExplained'].get('resource'), '')}"],
    ]))
    w("")
    cpe = g.get("criticalPathExplained", {})
    w(f"**Вывод:** {cpe.get('conclusion', '')}.\n")

    # 2. Методика
    w(f"## 2. Как посчитан план ({H})\n")
    for st in cpe.get("steps", []):
        w(f"- {st}")
    ga = g.get("ganttAssumptions", {})
    w(f"- Тип расчёта: {ga.get('ganttType', '')}; календарь: {ga.get('calendar', '')}.")
    w(f"- Исключено из ганта: {ga.get('excludedFromGantt', '')}.")
    w("- Роль задачи берётся из префикса в названии: [BA], [ARC], [DS], [BE], [FE], [QA], [ORG], [DVO]. "
      "Задача без однозначного префикса получает роль OTHER и планируется на руководителя проекта.")
    w("- Готовые задачи стоят по факту; задачи «в работе» планируются на остаток (оценка − списано); "
      "незавершённые задачи не могут начинаться раньше сегодняшнего дня; каждый исполнитель берёт следующую "
      "готовую к старту задачу из очереди своей роли по приоритету эпика.\n")
    exc = ga.get("excludedScenarios") or []
    if exc:
        w("Сценарии, сознательно не включённые в план (нет оценки / делаются по ходу):\n")
        w(table(["Код", "Группа", "Сценарий", "Почему не в плане"], [[x.get("code"), x.get("group"), x.get("name"), x.get("reason")] for x in exc]))
        w("")

    # 3. Динамика по слепкам
    w(f"## 3. Динамика плана по обновлениям ({H})\n")
    rows = []
    for b in d.get("baselines", []):
        if not (b.get("nItems") or 0) and not b.get("criticalEnd"):
            continue
        rows.append([ddmmyy((b.get("ts") or "")[:10]), b.get("label", ""), ddmmyy(b.get("criticalEnd")),
                     h(b.get("hoursTotal")) if b.get("hoursTotal") else "—", h(b.get("hoursSpent")) if b.get("hoursSpent") else "—"])
    w(table(["Дата слепка", "Слепок", "Окончание плана", "Объём, ч", "Списано, ч"], rows))
    w("\nДо 20.08.2026 в план входил весь бэклог 19 эпиков (не только MVP), поэтому даты окончания 2028–2040 "
      "несопоставимы с текущими; с 20.08.2026 — только MVP-скоуп, с 21.09.2026 — 10 согласованных эпиков.\n")

    # 4. Что изменилось
    if cmp:
        sm = cmp["summary"]
        w(f"## 4. Что изменилось с прошлого обновления ({H}, сравнение со слепком «{cmp['baseline']['label']}»)\n")
        for line in cmp["sentences"]:
            w(f"- {line}")
        w(f"- Объём плана: {h(sm.get('hours0'))} → {h(sm.get('hours1'))} ч; списано: {h(sm.get('spent0'))} → {h(sm.get('spent1'))} ч "
          f"(+{h((sm.get('spent1') or 0) - (sm.get('spent0') or 0))} ч за период).")
        w(f"- Задачи: сдвинулись позже {sm['nLater']}, раньше {sm['nEarlier']}, без сдвига {sm['nSame']}, новых {sm['nNew']}, убрано {sm['nRemoved']}.\n")
        cats = sorted([c for c in cmp["cats"] if c["code"] != "QUEUE" or c["impacted"]], key=lambda c: (-(c["impacted"] or 0), -(c["n"] or 0)))
        if cats:
            w("Корневые причины сдвига:\n")
            w(table(["Причина", "Задач", "Часы", "Повлияла на задач (позже/раньше)", "Макс. сдвиг", "Задачи"],
                    [[c["label"], c["n"] or "—", h(c["hours"]) if c["hours"] else "—",
                      f"{c['impacted']} ({c['later']}/{c['earlier']})" if c["impacted"] else "—",
                      shift_txt(c["maxShift"]) if c["impacted"] else "—", ", ".join(c["keys"])] for c in cats]))
            w("")
        ep = [r for r in cmp["items"] if r["type"] == "epic" and r["cEnd"]]
        ep.sort(key=lambda r: -(r["dEnd"] or 0))
        w("Сдвиг окончания эпиков:\n")
        w(table(["Эпик", "Было", "Стало", "Сдвиг", "Почему"],
                [[f"{r['key']} {r['summary']}", ddmmyy(r["bEnd"]), ddmmyy(r["cEnd"]),
                  shift_txt(r["dEnd"]) if r["state"] != "new" else "новый", r["why"] or "—"] for r in ep]))
        w("")
        rs = [r for r in sm.get("resources", []) if r.get("rem0") or r.get("rem1")]
        rs.sort(key=lambda r: r.get("end1") or "", reverse=True)
        w("Очереди исполнителей (остаток работы и конец очереди):\n")
        w(table(["Исполнитель", "Остаток было, ч", "Остаток стало, ч", "Конец было", "Конец стало"],
                [[r["name"], h(r.get("rem0")), h(r.get("rem1")), ddmmyy(r.get("end0")), ddmmyy(r.get("end1"))] for r in rs]))
        w("")
        new_t = [r for r in cmp["items"] if r["type"] == "task" and r["state"] == "new"]
        rem_t = [r for r in cmp["items"] if r["type"] == "task" and r["state"] == "removed"]
        if new_t:
            w("Новые задачи с прошлого обновления: " + "; ".join(f"{r['key']} {r['summary']}" for r in new_t) + ".\n")
        if rem_t:
            w("Убраны из плана: " + "; ".join(f"{r['key']} {r['summary']}" for r in rem_t) + ".\n")

    # 5. Эпики
    w(f"## 5. Эпики MVP: прогресс и сроки ({H})\n")
    rows = []
    for e in epics:
        et = [t for t in tasks if t["epic"] == e["key"]]
        n_done = sum(t["category"] == "done" for t in et)
        n_wip = sum(t["category"] == "in_progress" for t in et)
        n_bl = sum(t["category"] == "backlog" for t in et)
        by_dl = sum(t["category"] == "done" or (t.get("end") or "9") <= DEADLINE for t in et)
        est, sp = e.get("estimateH") or 0, e.get("spentH") or 0
        st = "Готово" if et and n_done == len(et) else "В работе" if (n_done or n_wip) else "Не начато"
        sh = shift.get(e["key"])
        rows.append([e["key"], e["summary"], e.get("priority"), st, f"{n_done}/{n_wip}/{n_bl}",
                     f"{e.get('storiesDone', 0)}/{e.get('storiesTotal', 0)}", h(est), h(sp),
                     f"{round(sp / est * 100) if est else 0}%", ddmmyy(e.get("start")), ddmmyy(e.get("end")),
                     "да" if (e.get("end") or "9") <= DEADLINE else "нет", f"{by_dl}/{len(et)}",
                     shift_txt(sh["dEnd"]) if sh and sh["state"] != "new" else "—"])
    w(table(["Ключ", "Эпик", "Приоритет", "Статус", "Задачи готово/в работе/не начато", "Стори готово/всего",
             "План, ч", "Списано, ч", "Списано от плана", "Начало", "Окончание", "Успевает к 10.12", "Задач к 10.12", "Сдвиг с прошлого"], rows))
    w("\n«Списано от плана» > 100% — перерасход часов относительно оценки.\n")

    # 5а. Сценарии и спринты (с 20.10.2026) — для ответа «на какой стадии сценарий»
    scs = g.get("scenarios") or []
    sps = g.get("sprints") or []
    sp = lambda n: "—" if n is None else ("до С0" if n < 0 else f"С{n}")
    if sps:
        w(f"## 5а. Спринты ({H})\n")
        w("Спринт — ровно 2 недели; Спринт 4 = 20.10–03.11.2026, Спринт 0 = 25.08–08.09.2026. Завершённая задача из "
          "закрытого спринта стоит на ганте с датой окончания этого спринта (в т.ч. «Waiting for release» — для команды это готово); "
          "если задача закрыта раньше начала спринта по этому календарю — с фактической датой.\n")
        w(table(["Спринт", "Начало", "Конец", "Состояние"],
                [[s["name"], ddmmyy(s["start"]), ddmmyy(s["end"]),
                  {"closed": "закрыт", "active": "текущий", "future": "будущий"}.get(s["state"], s["state"])] for s in sps]))
        w("")
    if scs:
        w(f"## 5б. Сценарии MVP: текущий этап и прогноз по спринтам ({H})\n")
        w("Сценарии — из реестра Confluence 2356754448 «Реестр оценки скоупа MVP v.2». Стори привязана к сценарию по метке Jira "
          "(OB1, PL9…), иначе по префиксу названия, иначе по таблице «Структура и оценка» реестра, иначе по логической привязке; "
          "непривязанное — «Платформа». Этапы: Аналитика ([BA]+[ARC]) → Дизайн [DS] ∥ Бэк [BE] → Фронт [FE] → QA; "
          "прошлое — факт Jira, будущее — прогноз планировщика. «Сейчас» — этапы с задачами в работе (или следующий незавершённый).\n")
        rows = []
        for c in scs:
            stg = "; ".join(f"{x['name']} {sp(x['startSprint'])}–{sp(x['endSprint'])} ({h(x['doneH'])}/{h(x['estimateH'])} ч)"
                            for x in c.get("stages") or []) or "—"
            if c.get("tasks") and c.get("missingStages"):
                names = {"AN": "Аналитика", "BE": "Бэк", "QA": "QA"}
                stg += "; НЕТ задач обязательного этапа: " + ", ".join(names.get(m, m) for m in c["missingStages"])
            rows.append([c["code"], c["name"], c.get("contour") or "", c.get("priority") or "", c.get("current") or "",
                         f"{c.get('tasksDone', 0)}/{c.get('tasks', 0)}", h(c.get("estimateH")),
                         f"{sp(c.get('readySprint'))} ({ddmmyy(c.get('end'))})" if c.get("end") else "—",
                         ("да" if c.get("onTime") else "нет") if c.get("end") else "—", stg])
        w(table(["Код", "Сценарий", "Контур", "P", "Сейчас", "Задач готово/всего", "План, ч", "Готов к спринту", "Успевает к 10.12", "Этапы (спринты, ч готово/план)"], rows))
        w("")

    # 6. Команда
    w(f"## 6. Команда и загрузка ({H})\n")
    tc = d.get("teamConfluence") or {}
    if tc.get("members"):
        w(f"Источник состава: {tc.get('source', '')}, снят {ddmmyy((tc.get('collectedAt') or '')[:10])}.\n")
        w(table(["Сотрудник", "Роль", "Код", "Участие", "С даты", "Статус", "Комментарий"],
                [[m["name"], m["roleTitle"], m["role"], f"{m['pct']}%", ddmmyy(m.get("from")), TEAM_ST.get(m["status"], m["status"]), m.get("note", "")]
                 for m in tc["members"]]))
        w("")
    rows = []
    for r in g.get("resources", []):
        rt = [t for t in tasks if t.get("resource") == r["id"]]
        op = [t for t in rt if t["category"] != "done"]
        rows.append([r["id"], r["name"], ROLE_TITLE.get(r["role"], r["role"]), len(rt), len(op),
                     h(sum(t.get("estimateH") or 0 for t in rt)), h(sum(t.get("spentH") or 0 for t in rt)),
                     h(sum(remaining(t) for t in op)), ddmmyy(max([t["end"] for t in op if t.get("end")], default=""))])
    w("Исполнители в расчёте ганта:\n")
    w(table(["Ресурс", "Исполнитель", "Роль", "Задач всего", "Не завершено", "План, ч", "Списано, ч", "Остаток, ч", "Загружен до"], rows))
    w("")
    rp = g.get("resourcePlan") or d.get("resourcePlan") or []
    months = sorted({m["month"] for r in rp for m in r.get("months", []) if m["month"] >= gen[:7]})
    if months:
        w("Плановая загрузка по месяцам, % от нормы рабочих часов (с текущего месяца):\n")
        w(table(["Исполнитель"] + [f"{m[5:7]}.{m[:4]}" for m in months],
                [[two(r["name"])] + [next((f"{x['loadPct']}%" for x in r["months"] if x["month"] == m), "—") for m in months] for r in rp]))
        w("")
    by_role = defaultdict(lambda: [0, 0, 0])
    for t in tasks:
        a = by_role[t["role"]]
        a[0] += t.get("estimateH") or 0
        a[1] += t.get("spentH") or 0
        a[2] += remaining(t)
    w("Объём по ролям:\n")
    w(table(["Роль", "План, ч", "Списано, ч", "Остаток, ч"],
            [[f"{k} ({ROLE_TITLE.get(k, k)})", h(v[0]), h(v[1]), h(v[2])] for k, v in sorted(by_role.items(), key=lambda x: -x[1][0])]))
    w("")

    # 7. Скоуп MVP
    ms = g.get("mvpScope") or {}
    w(f"## 7. Скоуп MVP: какие стори успевают к 10.12.2026 ({H})\n")
    w(f"{ms.get('rationale', '')} Успевают: {len(ms.get('inStories', []))} стори, не успевают: {len(ms.get('outStories', []))}.\n")
    for title, key in (("Успевают к дедлайну", "inStories"), ("Не успевают к дедлайну", "outStories")):
        lst = sorted(ms.get(key, []), key=lambda x: x.get("readyDate") or "")
        w(f"{title}:\n")
        w(table(["Стори", "Эпик", "Название", "Готовность по плану"],
                [[x["key"], epic_name.get(next((s["epic"] for s in stories if s["key"] == x["key"]), ""), ""), x["name"], ddmmyy(x.get("readyDate"))] for x in lst]))
        w("")

    # 8. Детальный план
    w(f"## 8. Детальный план: эпик → стори → задачи ({H})\n")
    w("Формат строки задачи: ключ · роль · название · исполнитель · статус Jira · оценка/списано ч · начало–окончание по плану · "
      "критпуть · сдвиг окончания с прошлого обновления и причина.\n")
    for e in epics:
        w(f"### Эпик {e['key']} «{e['summary']}» ({H})\n")
        w(f"Приоритет {e.get('priority')}; план {h(e.get('estimateH'))} ч, списано {h(e.get('spentH'))} ч; "
          f"стори готово {e.get('storiesDone', 0)} из {e.get('storiesTotal', 0)}; сроки {ddmmyy(e.get('start'))} – {ddmmyy(e.get('end'))}"
          f"{'; на критпути' if e['key'] in crit_keys else ''}.\n")
        groups = sorted(st_by_epic.get(e["key"], []), key=lambda s: (s.get("start") or "", s["key"]))
        for st in groups + [None]:
            if st is None:
                tl = t_by_story.get("E:" + e["key"], [])
                tl = [t for t in tl if not t.get("parent")]
                if not tl:
                    continue
                w(f"#### Задачи эпика {e['key']} без стори\n")
            else:
                tl = t_by_story.get(st["key"], [])
                sh = shift.get(st["key"])
                mvp = "успевает к 10.12" if st["key"] in mvp_in else "не успевает к 10.12"
                w(f"#### Стори {st['key']} «{st['summary']}» (эпик «{e['summary']}»)\n")
                w(f"Статус: {CAT_RU.get(st['category'], st['category'])}; план {h(st.get('estimateH'))} ч, списано {h(st.get('spentH'))} ч; "
                  f"{ddmmyy(st.get('start'))} – {ddmmyy(st.get('end'))}; {mvp}"
                  f"{('; сценарий ' + st['scenario']) if st.get('scenario') else ''}"
                  f"{'; на критпути' if st['key'] in crit_keys else ''}"
                  f"{('; сдвиг ' + shift_txt(sh['dEnd']) + (' — ' + sh['why'] if sh['why'] else '')) if sh and sh.get('dEnd') else ''}.\n")
                if not tl:
                    w("Задач с оценкой нет.\n")
                    continue
            for t in sorted(tl, key=lambda t: (t.get("start") or "", t["key"])):
                # У готовых задач дата окончания — факт, «сдвиг» от перестроения очереди
                # для них шум; оставляем только закрытие раньше/позже плана.
                sh = shift.get(t["key"])
                if sh and t["category"] == "done" and sh.get("root") not in ("DONE_EARLY", "DONE_LATE"):
                    sh = None
                stxt = ""
                if sh:
                    if sh["state"] == "new":
                        stxt = " · новая с прошлого обновления"
                    elif sh.get("dEnd"):
                        stxt = f" · сдвиг {shift_txt(sh['dEnd'])}" + (f" ({sh['why']})" if sh["why"] else "")
                w(f"- {t['key']} · {t['role']} · {t['summary']} · {res_name.get(t.get('resource'), '—')} · {t['status']} "
                  f"({CAT_RU.get(t['category'], t['category'])}) · {h(t.get('estimateH'))}/{h(t.get('spentH'))} ч · "
                  f"{ddmmyy(t.get('start'))}–{ddmmyy(t.get('end'))}{' · критпуть' if t.get('onCriticalPath') else ''}{stxt}")
            w("")

    # 9. Вехи, блокеры, риски (ручные разделы дашборда)
    w(f"## 9. Вехи, блокеры, риски, допущения, открытые вопросы ({H})\n")
    w("Эти разделы ведутся на дашборде вручную и при обновлении из Jira не пересчитываются — могут отставать от факта; "
      "при расхождении приоритет у разделов 1–8.\n")
    if d.get("milestones"):
        w("Вехи:\n")
        w(table(["Дата", "Веха", "Статус"], [[ddmmyy(m["date"]), m["label"], m["status"]] for m in d["milestones"]]))
        w("")
    if d.get("blockersNow"):
        w("Блокеры:\n")
        w(table(["Блокер", "Ответственный", "С даты", "Источник"], [[b["text"], b.get("owner"), ddmmyy(b.get("since")), b.get("source")] for b in d["blockersNow"]]))
        w("")
    if d.get("risks"):
        w("Риски (вероятность и влияние по шкале 1–5):\n")
        w(table(["ID", "Риск", "Вер.", "Влияние", "Митигация", "Владелец"], [[r["id"], r["desc"], r.get("prob"), r.get("impact"), r.get("mitigation"), r.get("owner")] for r in d["risks"]]))
        w("")
    if d.get("assumptions"):
        w("Допущения:\n")
        w(table(["ID", "Допущение", "Влияние", "Владелец"], [[a["id"], a["desc"], a.get("impact"), a.get("owner")] for a in d["assumptions"]]))
        w("")
    if d.get("questions"):
        w("Открытые вопросы:\n")
        w(table(["ID", "Вопрос", "Ответственный", "Срок", "Статус"], [[q["id"], q["question"], q.get("owner"), q.get("deadline"), q.get("status")] for q in d["questions"]]))
        w("")

    w(f"## 10. Справочник ({H})\n")
    w("Роли: " + "; ".join(f"{k} — {v}" for k, v in ROLE_TITLE.items()) + ".")
    cats = defaultdict(set)
    for t in tasks:
        cats[t["category"]].add(t["status"])
    w("Категории статусов Jira в плане: " + "; ".join(f"{CAT_RU.get(k, k)} — {', '.join(sorted(v))}" for k, v in cats.items()) + ".")
    w("Дашборд: https://b2bapp-dashboard.vercel.app (страницы: Диаграмма Ганта со сравнением слепков, Скоуп MVP, Ресурсы). "
      "Jira: https://btask.beeline.ru/browse/<ключ задачи>.")
    return "\n".join(out) + "\n"


def main():
    repo = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(repo, "public", "data", "data.json"))
    ap.add_argument("--out", default=os.path.join(repo, "rag", "MASTER_11_план_работ.md"))
    ap.add_argument("--copy-to", nargs="*", default=[])
    a = ap.parse_args()
    d = json.load(open(a.data, encoding="utf-8"))
    gen = (d["ganttV2"].get("generatedAt") or d.get("refreshedAt") or date.today().isoformat())[:10]
    bl = previous_baseline(d, gen)
    cmp = run_compare(repo, os.path.abspath(a.data), bl)
    if bl and not cmp:
        print("ВНИМАНИЕ: анализ сдвигов не построен — раздел 4 пропущен", file=sys.stderr)
    text = build(d, cmp)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(text)
    print(f"OK {a.out}: {len(text)} симв., {text.count(chr(10))} строк; сравнение со слепком: {bl['label'] if cmp else 'нет'}")
    for dst in a.copy_to:
        os.makedirs(dst, exist_ok=True)
        p = os.path.join(dst, os.path.basename(a.out))
        shutil.copyfile(a.out, p)
        print("copied ->", p)


if __name__ == "__main__":
    main()
