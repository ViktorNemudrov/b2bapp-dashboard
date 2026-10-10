// Сравнение текущего ганта со слепком (baseline): что куда сдвинулось и ПОЧЕМУ.
// Запрос Виктора 03.10.2026: при выборе прошлого слепка гант должен показывать
// прошлый план пунктиром поверх текущего, сдвиг по каждой задаче/стори/эпику
// и короткое текстовое объяснение причины сдвига.
//
// Причины восстанавливаются той же логикой, что у планировщика build_dashboard.py:
// задача начинается не раньше (а) конца работ ролей, от которых она зависит
// внутри стори (BA → ARC → DS∥BE → FE → QA, см. ROLE_DEPS в build_dashboard.py),
// (б) освобождения исполнителя (очередь), (в) сегодня.
// Длительность = остаток работы (бэклог — оценка, в работе — оценка − списано).
// Поэтому у сдвига есть либо «собственная» причина (новая задача, переоценка,
// перерасход, не сделана к плановой дате, смена исполнителя, закрыта раньше),
// либо он унаследован по цепочке ожидания от другой задачи — тогда идём по
// цепочке до задачи с собственной причиной (корневая причина).
const GC = (() => {
  const DEPS = {BA:[], ARC:['BA'], DS:['BA','ARC'], BE:['BA','ARC'], FE:['BA','ARC','DS','BE'], QA:['BA','ARC','BE','FE']};
  let blPromise = null;

  function loadBaselines(){
    if(!blPromise){
      blPromise = fetch('../data/baselines.json?t='+Date.now())
        .then(r => r.ok ? r.json() : {baselines: []})
        .then(j => j.baselines || [])
        .catch(() => []);
    }
    return blPromise;
  }

  const iso = d => d ? String(d).slice(0, 10) : '';
  const ddmm = s => s ? `${s.slice(8,10)}.${s.slice(5,7)}` : '—';
  const ddmmyy = s => s ? `${s.slice(8,10)}.${s.slice(5,7)}.${s.slice(0,4)}` : '—';
  const h = x => Math.round((x || 0) * 10) / 10;
  const firstName = n => (n || '').split(' ').slice(0, 2).join(' ');
  // 1 задача, 2 задачи, 5 задач
  const tasksN = n => { const a = Math.abs(n) % 100, b = a % 10; return `${n} ${a > 10 && a < 20 ? 'задач' : b === 1 ? 'задача' : b >= 2 && b <= 4 ? 'задачи' : 'задач'}`; };

  function makeWorkdays(holidays){
    const H = new Set(holidays || []);
    const isWork = dt => { const g = dt.getUTCDay(); return g !== 0 && g !== 6 && !H.has(dt.toISOString().slice(0,10)); };
    // Разница в рабочих днях между датами a→b со знаком (как сдвинулся конец).
    function diff(a, b){
      if(!a || !b || a === b) return 0;
      let x = new Date(a + 'T00:00:00Z'), y = new Date(b + 'T00:00:00Z');
      const sign = y > x ? 1 : -1;
      if(sign < 0) [x, y] = [y, x];
      let n = 0;
      for(const d = new Date(x); d < y; d.setUTCDate(d.getUTCDate() + 1)){
        const nd = new Date(d); nd.setUTCDate(nd.getUTCDate() + 1);
        if(isWork(nd)) n++;
      }
      return sign * n;
    }
    function nextWork(s){
      const d = new Date(s + 'T00:00:00Z');
      while(!isWork(d)) d.setUTCDate(d.getUTCDate() + 1);
      return d.toISOString().slice(0, 10);
    }
    return {diff, nextWork};
  }

  const remaining = it => !it ? 0 : it.category === 'done' ? 0
    : it.category === 'in_progress' ? Math.max((it.estimateH || 0) - (it.spentH || 0), 0) : (it.estimateH || 0);

  const fmtDays = n => n > 0 ? `+${n} раб. дн.` : n < 0 ? `−${-n} раб. дн.` : 'без сдвига';

  // Основной расчёт. bl — объект слепка из baselines.json, gv — текущий ganttV2.
  function compare(bl, gv, resourceNames){
    const W = makeWorkdays(gv.workCalendar && gv.workCalendar.holidays);
    const snap = iso(gv.generatedAt) || new Date().toISOString().slice(0, 10);
    const blDate = iso(bl.ts);
    const B = {}, C = {};
    (bl.items || []).forEach(i => B[i.key] = i);
    gv.items.forEach(i => C[i.key] = i);
    const detailed = (bl.items || []).some(i => i.type && i.estimateH != null);
    const nameOf = (it) => it ? (it.resourceName || resourceNames[it.resource] || it.resource || '—') : '—';

    // Текущий план: очередь каждого исполнителя и конец фаз каждой стори.
    const tasks = gv.items.filter(i => i.type === 'task');
    const byRes = {};
    tasks.forEach(t => { if(t.resource) (byRes[t.resource] = byRes[t.resource] || []).push(t); });
    Object.values(byRes).forEach(a => a.sort((x, y) => x.start < y.start ? -1 : x.start > y.start ? 1 : x.end < y.end ? -1 : 1));
    const byStory = {};
    tasks.forEach(t => { if(t.parent) (byStory[t.parent] = byStory[t.parent] || []).push(t); });
    const floorDay = W.nextWork(snap);

    const res = {};  // key -> результат
    const taskInfo = key => res[key];

    function shiftOf(key){
      const b = B[key], c = C[key];
      if(!b || !c || !b.end || !c.end) return null;
      return W.diff(b.end, c.end);
    }

    // Что держит начало задачи в текущем плане (связующее ограничение).
    function binding(c){
      if(c.category === 'done' || !c.start) return null;
      let best = null;
      const deps = DEPS[c.role];
      if(deps && deps.length && c.parent && byStory[c.parent]){
        byStory[c.parent].forEach(t => {
          if(t.key === c.key || !deps.includes(t.role) || !t.end) return;
          if(t.end <= c.start && (!best || t.end > best.task.end)) best = {kind: 'dep', task: t};
        });
      }
      const q = byRes[c.resource] || [];
      let prev = null;
      for(const t of q){ if(t.key !== c.key && t.end && t.end <= c.start && t.start <= c.start) prev = (!prev || t.end > prev.end) ? t : prev; }
      if(prev && (!best || prev.end > best.task.end)) best = {kind: 'queue', task: prev};
      // Связующее, только если начало реально упирается в него (≤ 2 раб. дня зазора).
      if(best && W.diff(best.task.end, c.start) > 2) best = null;
      if(!best && c.start <= floorDay) return {kind: 'today'};
      return best;
    }

    // Собственные причины изменения задачи (без учёта ожидания).
    function ownReasons(b, c){
      const r = [];
      if(!b){ r.push({code: 'NEW', text: `новая задача в плане (+${h(c.estimateH)} ч, ${c.role || '—'})`, hours: c.estimateH || 0}); return r; }
      if(!detailed) return r;
      const est0 = b.estimateH || 0, est1 = c.estimateH || 0;
      if(c.category === 'done' && b.category !== 'done'){
        const d = W.diff(b.end, c.end);
        const spentNote = c.spentH && est1
          ? (c.spentH > est1 * 1.05 ? `, списано ${h(c.spentH)} ч при оценке ${h(est1)} ч`
            : c.spentH < est1 * 0.8 ? `, списано ${h(c.spentH)} ч из ${h(est1)} ч — оценка была с запасом` : '')
          : '';
        if(d < 0) r.push({code: 'DONE_EARLY', text: `закрыта ${ddmm(c.end)} — раньше плана${spentNote}`, hours: remaining(b)});
        else if(d > 0) r.push({code: 'DONE_LATE', text: `закрыта ${ddmm(c.end)} вместо плановых ${ddmm(b.end)}${spentNote}`, hours: Math.max((c.spentH || 0) - est0, 0)});
        else r.push({code: 'DONE', text: `закрыта в срок${spentNote}`, hours: 0});
        return r;
      }
      if(c.category === 'done') return r;
      if(Math.abs(est1 - est0) >= 0.5) r.push({code: 'EST', text: `оценка изменилась: ${h(est0)} → ${h(est1)} ч (${est1 > est0 ? '+' : '−'}${h(Math.abs(est1 - est0))} ч)`, hours: est1 - est0});
      if((c.spentH || 0) > est1 && est1 > 0 && !((b.spentH || 0) > est0))
        r.push({code: 'OVERRUN', text: `перерасход: списано ${h(c.spentH)} ч при оценке ${h(est1)} ч`, hours: (c.spentH || 0) - est1});
      if(b.resource && c.resource && b.resource !== c.resource)
        // Внутри роли исполнителя выбирает планировщик (кто раньше свободен), а не
        // assignee из Jira — поэтому это «перераспределение в плане», не переназначение.
        r.push({code: 'RES', text: b.role === c.role
          ? `в плане переложена между исполнителями роли ${c.role}: ${firstName(nameOf(b))} → ${firstName(nameOf(c))}`
          : `исполнитель: ${firstName(nameOf(b))} → ${firstName(nameOf(c))}`, hours: 0});
      // Не сделано к дате, к которой по прошлому плану должно было быть сделано/начато.
      if(b.start && b.start < snap){
        const progressed = (c.spentH || 0) - (b.spentH || 0);
        const rem = remaining(c);
        if(b.end && b.end < snap)
          r.push({code: 'LAG', text: `по плану от ${ddmm(blDate)} должна была закончиться к ${ddmm(b.end)}, на ${ddmm(snap)} ${c.category !== 'in_progress' ? 'не начата' : rem > 0 ? `в работе, осталось ${h(rem)} ч` : `в работе, оценка уже выбрана (списано ${h(c.spentH)} из ${h(c.estimateH)} ч)`}`, hours: rem});
        else if(c.category !== 'in_progress' && progressed <= 0)
          r.push({code: 'LAG', text: `по плану должна была начаться ${ddmm(b.start)}, на ${ddmm(snap)} не начата`, hours: Math.min(rem, (c.estimateH || 0))});
      }
      if(c.category === 'in_progress' && b.category !== 'in_progress' && !r.length)
        r.push({code: 'STARTED', text: `взята в работу (списано ${h(c.spentH)} ч из ${h(est1)} ч)`, hours: 0});
      return r;
    }

    // Как изменился объём работы в очереди исполнителя ДО этой задачи.
    function queueGrowth(c, b){
      if(!detailed || !b || !c.resource) return null;
      const before = (byRes[c.resource] || []).filter(t => t.key !== c.key && t.start < c.start && t.category !== 'done');
      const items = [];
      before.forEach(t => {
        const bt = B[t.key];
        if(!bt) items.push({key: t.key, why: 'новая', h: remaining(t)});
        else if(bt.resource !== t.resource) items.push({key: t.key, why: `перешла от ${firstName(nameOf(bt))}`, h: remaining(t)});
        else if((t.estimateH || 0) - (bt.estimateH || 0) >= 0.5) items.push({key: t.key, why: `оценка +${h(t.estimateH - bt.estimateH)} ч`, h: t.estimateH - bt.estimateH});
        else if((t.spentH || 0) > (t.estimateH || 0) && (t.estimateH || 0) > 0) items.push({key: t.key, why: 'перерасход', h: 0});
      });
      items.sort((x, y) => y.h - x.h);
      return items.length ? items : null;
    }

    // 1) задачи: сдвиг + собственные причины + связующее ограничение
    const allKeys = new Set([...Object.keys(C), ...Object.keys(B)]);
    allKeys.forEach(key => {
      const b = B[key], c = C[key];
      const type = (c && c.type) || (b && b.type) || 'task';
      if(type !== 'task') return;
      if(!c){ res[key] = {key, type, b, c: null, state: 'removed', dEnd: null, own: [{code: 'REMOVED', text: `убрана из плана (−${h(remaining(b))} ч)`, hours: remaining(b)}]}; return; }
      const dEnd = shiftOf(key), dStart = b && b.start && c.start ? W.diff(b.start, c.start) : null;
      res[key] = {key, type, b, c, dEnd, dStart, state: !b ? 'new' : dEnd ? 'moved' : 'same', own: ownReasons(b, c), bind: binding(c)};
    });

    // 2) корневая причина: идём по цепочке связующих ограничений
    function rootOf(key, depth = 0, seen = new Set()){
      const r = res[key];
      if(!r || seen.has(key) || depth > 40) return null;
      seen.add(key);
      const strong = r.own.find(o => o.code !== 'STARTED' && o.code !== 'DONE');
      if(strong && (r.state === 'new' || r.dEnd)) return {key, code: strong.code, text: strong.text};
      if(r.bind && r.bind.task){
        const up = res[r.bind.task.key];
        if(up && (up.dEnd || up.state === 'new')) return rootOf(r.bind.task.key, depth + 1, seen) || {key, code: 'QUEUE', text: ''};
      }
      if(r.bind && r.bind.kind === 'today' && r.dEnd > 0) return {key, code: 'TODAY', text: 'прошло время: начало не раньше сегодняшнего дня'};
      if(strong) return {key, code: strong.code, text: strong.text};
      return null;
    }

    Object.values(res).forEach(r => {
      if(r.state === 'removed') return;
      const parts = r.own.map(o => o.text);
      if(r.bind && r.dStart){
        const t = r.bind.task;
        if(r.bind.kind === 'dep'){
          const sd = res[t.key] && res[t.key].dEnd;
          parts.push(`ждёт ${t.key} (${t.role} — от неё зависит ${r.c.role} в этой стори)${sd ? `, которая сдвинулась на ${fmtDays(sd)}` : res[t.key] && res[t.key].state === 'new' ? ' — новая задача' : ''}`);
        } else if(r.bind.kind === 'queue'){
          const sd = res[t.key] && res[t.key].dEnd;
          const g = queueGrowth(r.c, r.b);
          let s = `в очереди у ${firstName(nameOf(r.c))} после ${t.key}${sd ? ` (сдвинулась на ${fmtDays(sd)})` : res[t.key] && res[t.key].state === 'new' ? ' (новая задача)' : ''}`;
          if(g){
            const add = g.reduce((a, x) => a + Math.max(x.h, 0), 0);
            s += `; перед ней в очереди ${add >= 1 ? `+${h(add)} ч работы: ` : ''}${g.slice(0, 3).map(x => `${x.key} — ${x.why}`).join(', ')}${g.length > 3 ? ` и ещё ${g.length - 3}` : ''}`;
          }
          parts.push(s);
        } else if(r.bind.kind === 'today' && r.dStart > 0){
          parts.push(`начало перенесено на ${ddmm(r.c.start)}: раньше сегодняшнего дня план не ставит`);
        }
      }
      r.root = rootOf(r.key);
      r.why = parts.join('; ') || (r.dEnd ? 'сдвиг из-за перестроения очереди (детали в слепке недоступны)' : '');
    });

    // 3) стори и эпики: сдвиг конца + какая задача его определяет
    const kidsOf = {};
    [...Object.values(C), ...Object.values(B)].forEach(i => {
      if(i.type === 'task' && i.parent) (kidsOf[i.parent] = kidsOf[i.parent] || new Set()).add(i.key);
      if(i.type === 'task' && i.epic) (kidsOf['E:' + i.epic] = kidsOf['E:' + i.epic] || new Set()).add(i.key);
    });
    allKeys.forEach(key => {
      const b = B[key], c = C[key];
      const type = (c && c.type) || (b && b.type);
      if(type !== 'story' && type !== 'epic') return;
      const kidKeys = [...(kidsOf[type === 'epic' ? 'E:' + key : key] || [])];
      const kids = kidKeys.map(k => res[k]).filter(Boolean);
      const cur = kids.filter(k => k.c && k.c.end).sort((x, y) => y.c.end.localeCompare(x.c.end))[0];
      // Стори/эпик без задач с оценкой в слепке: её дата там — заглушка (дата
      // создания), сравнивать нечего — это «новая работа», а не сдвиг на 70 дней.
      const hadWork = b && (detailed ? (b.estimateH || 0) > 0 : kids.some(k => k.b));
      let dEnd = null;
      if(hadWork && c && b.end && c.end) dEnd = W.diff(b.end, c.end);
      const nNew = kids.filter(k => k.state === 'new').length, nRem = kids.filter(k => k.state === 'removed').length;
      const hNew = kids.filter(k => k.state === 'new').reduce((a, k) => a + (k.c.estimateH || 0), 0);
      const est0 = b && b.estimateH != null ? b.estimateH : null, est1 = c ? c.estimateH : null;
      const parts = [];
      if(cur && dEnd) parts.push(`конец определяет ${cur.key} (${cur.c.role || '—'}): ${cur.why || fmtDays(cur.dEnd || 0)}`);
      if(nNew) parts.push(`добавлено задач: ${nNew} (+${h(hNew)} ч)`);
      if(nRem) parts.push(`убрано задач: ${nRem}`);
      if(est0 != null && est1 != null && Math.abs(est1 - est0) >= 1) parts.push(`объём ${h(est0)} → ${h(est1)} ч`);
      if(b && !hadWork && c) parts.unshift('в слепке не было задач с оценкой — работа добавлена после него');
      res[key] = {key, type, b: hadWork ? b : null, c, dEnd, state: !c ? 'removed' : !hadWork ? 'new' : dEnd ? 'moved' : 'same', why: parts.join('; '), driver: cur ? cur.key : null};
    });

    return {bl, snap, blDate, detailed, B, C, res, W, nameOf, summary: summarize()};

    // 4) сводка по проекту
    function summarize(){
      const T = Object.values(res).filter(r => r.type === 'task');
      const cat = {};
      const add = (code, r, hours) => {
        const k = cat[code] = cat[code] || {code, n: 0, hours: 0, keys: [], impacted: 0, maxShift: 0, later: 0, earlier: 0};
        k.n++; k.hours += hours || 0; k.keys.push(r.key);
      };
      T.forEach(r => r.own && r.own.forEach(o => { if(o.code !== 'STARTED' && o.code !== 'DONE') add(o.code, r, o.hours); }));
      T.forEach(r => {
        if(!r.root || !r.dEnd) return;
        const k = cat[r.root.code] = cat[r.root.code] || {code: r.root.code, n: 0, hours: 0, keys: [], impacted: 0, maxShift: 0, later: 0, earlier: 0};
        k.impacted++;
        if(r.dEnd > 0) k.later++; else k.earlier++;
        if(Math.abs(r.dEnd) > Math.abs(k.maxShift)) k.maxShift = r.dEnd;
      });
      const moved = T.filter(r => r.state !== 'removed' && r.state !== 'new');
      const later = moved.filter(r => r.dEnd > 0), earlier = moved.filter(r => r.dEnd < 0);
      const curEnd = gv.items.filter(i => i.type === 'task' && i.end).reduce((m, i) => i.end > m ? i.end : m, '');
      const blTasks = (bl.items || []).filter(i => (i.type || 'task') === 'task' && i.end);
      const blEnd = bl.criticalEnd || blTasks.reduce((m, i) => i.end > m ? i.end : m, '');
      const crit = gv.items.filter(i => i.type === 'task' && i.end === curEnd)[0];
      // Остаток работы по исполнителям: было/стало — именно он задаёт конец очереди.
      const byResRem = {};
      const bump = (id, name, side, it) => {
        const k = byResRem[name] = byResRem[name] || {name, id, rem0: 0, rem1: 0, end0: '', end1: ''};
        k['rem' + side] += remaining(it);
        if(it.end && it.end > k['end' + side]) k['end' + side] = it.end;
      };
      if(detailed) (bl.items || []).filter(i => i.type === 'task' && i.resource).forEach(i => bump(i.resource, firstName(nameOf(i)), 0, i));
      tasks.filter(i => i.resource).forEach(i => bump(i.resource, firstName(nameOf(i)), 1, i));
      return {
        blEnd, curEnd, dEnd: W.diff(blEnd, curEnd), crit: crit ? res[crit.key] : null,
        hours0: bl.hoursTotal, hours1: gv.items.filter(i => i.type === 'epic').reduce((a, i) => a + (i.estimateH || 0), 0),
        spent0: bl.hoursSpent, spent1: gv.items.filter(i => i.type === 'epic').reduce((a, i) => a + (i.spentH || 0), 0),
        nLater: later.length, nEarlier: earlier.length, nSame: moved.length - later.length - earlier.length,
        nNew: T.filter(r => r.state === 'new').length, nRemoved: T.filter(r => r.state === 'removed').length,
        cats: cat, resources: Object.values(byResRem),
      };
    }
  }

  const CAT_LABEL = {
    NEW: 'Новые задачи в плане', REMOVED: 'Убраны из плана', EST: 'Изменились оценки',
    OVERRUN: 'Перерасход (списано больше оценки)', LAG: 'Не сделано к плановой дате',
    DONE_LATE: 'Закрыты позже плана', DONE_EARLY: 'Закрыты раньше плана', RES: 'Перераспределение между исполнителями роли',
    TODAY: 'Прошло время (план не начинает работу в прошлом)', QUEUE: 'Перестроение очередей',
  };
  const CAT_HOURS = {NEW: 'ч добавлено', REMOVED: 'ч освобождено', EST: 'ч изменение оценок', OVERRUN: 'ч сверх оценок', LAG: 'ч перенесено вперёд', DONE_EARLY: 'ч освобождено', DONE_LATE: 'ч сверх оценок'};

  // Причина относится к «тянуло» или «ускорило» по фактическому направлению
  // сдвига задач, на которые она повлияла (смена исполнителя, например, чаще
  // ускоряет — работу забрал свободный человек).
  function sentence(cmp){
    const s = cmp.summary, c = s.cats;
    const dir = s.dEnd > 0 ? `сдвинулся позже на ${s.dEnd} раб. дн.` : s.dEnd < 0 ? `сдвинулся раньше на ${-s.dEnd} раб. дн.` : 'не изменился';
    const out = [`Конец плана ${dir}: ${ddmmyy(s.blEnd)} → ${ddmmyy(s.curEnd)}.`];
    const phrase = {
      NEW: k => `в план добавлено: ${tasksN(k.n)} (+${h(k.hours)} ч)`,
      LAG: k => `${tasksN(k.n)} по плану от ${ddmm(cmp.blDate)} должны были быть сделаны или начаты к ${ddmm(cmp.snap)}, но не выполнены — ${h(k.hours)} ч работы перенесено вперёд`,
      EST: k => `переоценено: ${tasksN(k.n)} (${k.hours >= 0 ? '+' : '−'}${h(Math.abs(k.hours))} ч в сумме)`,
      OVERRUN: k => `перерасход (списано больше оценки): ${tasksN(k.n)} (+${h(k.hours)} ч)`,
      DONE_LATE: k => `закрыты позже плана: ${tasksN(k.n)}`,
      DONE_EARLY: k => `закрыты раньше плана: ${tasksN(k.n)}`,
      RES: k => `перераспределение задач между исполнителями одной роли в плане: ${tasksN(k.n)}`,
      REMOVED: k => `убраны из плана: ${tasksN(k.n)} (−${h(k.hours)} ч)`,
      TODAY: k => `прошло время — работа, не сделанная к сегодня, перенесена вперёд`,
    };
    const ORDER = ['NEW', 'LAG', 'EST', 'OVERRUN', 'DONE_LATE', 'RES', 'DONE_EARLY', 'REMOVED', 'TODAY'];
    const pull = [], help = [];
    ORDER.forEach(code => {
      const k = c[code]; if(!k || !phrase[code]) return;
      const toEarlier = k.impacted ? k.earlier > k.later : (code === 'DONE_EARLY' || code === 'REMOVED');
      const p = phrase[code](k) + (k.impacted ? ` → повлияло на ${tasksN(k.impacted)}${k.later && k.earlier ? ` (позже ${k.later}, раньше ${k.earlier})` : ''}` : '');
      (toEarlier ? help : pull).push(p);
    });
    if(pull.length) out.push('Что тянуло план позже: ' + pull.join('; ') + '.');
    if(help.length) out.push('Что ускорило: ' + help.join('; ') + '.');
    if(s.crit && s.crit.c){
      const cr = s.crit;
      out.push(`Конец плана определяет ${cr.key} (${cr.c.role || '—'}, ${firstName(cmp.nameOf(cr.c))})${cr.why ? ': ' + cr.why : ''}.`);
    }
    return out;
  }

  function panelHtml(cmp, jiraLink){
    const s = cmp.summary;
    const cls = n => n > 0 ? 'gc-late' : n < 0 ? 'gc-early' : '';
    const badge = n => `<span class="gc-delta ${cls(n)}">${n > 0 ? '+' : n < 0 ? '−' : '±'}${Math.abs(n || 0)} дн.</span>`;
    const lines = sentence(cmp);
    const catRows = Object.values(s.cats).filter(k => k.code !== 'QUEUE' || k.impacted)
      .sort((a, b) => (b.impacted - a.impacted) || (b.n - a.n))
      .map(k => `<tr><td>${CAT_LABEL[k.code] || k.code}</td><td>${k.n || '—'}</td><td>${k.hours && CAT_HOURS[k.code] ? `${h(Math.abs(k.hours))} ${CAT_HOURS[k.code]}` : '—'}</td>
        <td>${k.impacted ? `${tasksN(k.impacted)}${k.later && k.earlier ? ` (позже ${k.later} / раньше ${k.earlier})` : ''}, макс. ${badge(k.maxShift)}` : '—'}</td>
        <td class="gc-keys">${k.keys.slice(0, 6).map(jiraLink).join(', ')}${k.keys.length > 6 ? ` +${k.keys.length - 6}` : ''}</td></tr>`).join('');
    const epics = Object.values(cmp.res).filter(r => r.type === 'epic' && r.c)
      .sort((a, b) => (b.dEnd || 0) - (a.dEnd || 0))
      .map(r => `<tr><td>${jiraLink(r.key)} ${(r.c.summary || '').slice(0, 40)}</td><td>${ddmmyy(r.b && r.b.end)}</td><td>${ddmmyy(r.c.end)}</td><td>${r.b ? badge(r.dEnd) : '<span class="gc-delta gc-new">новый</span>'}</td><td class="gc-why">${r.why || '—'}</td></tr>`).join('');
    const resRows = s.resources.filter(r => r.rem0 || r.rem1).sort((a, b) => (b.end1 || '').localeCompare(a.end1 || ''))
      .map(r => `<tr><td>${r.name}</td><td>${cmp.detailed ? h(r.rem0) + ' ч' : '—'}</td><td>${h(r.rem1)} ч</td><td>${ddmmyy(r.end0)}</td><td>${ddmmyy(r.end1)}</td><td>${r.end0 ? badge(cmp.W.diff(r.end0, r.end1)) : '—'}</td></tr>`).join('');
    const top = Object.values(cmp.res).filter(r => r.type === 'task' && r.c && r.b && r.dEnd)
      .sort((a, b) => Math.abs(b.dEnd) - Math.abs(a.dEnd)).slice(0, 15)
      .map(r => `<tr><td>${jiraLink(r.key)}</td><td>${r.c.role || '—'}</td><td>${(r.c.summary || '').slice(0, 46)}</td><td>${badge(r.dEnd)}</td><td class="gc-why">${r.why || '—'}</td></tr>`).join('');
    const removed = Object.values(cmp.res).filter(r => r.type === 'task' && r.state === 'removed');
    return `
      <div class="gc-head">📐 <b>Сравнение с «${cmp.bl.label || cmp.bl.id}»</b>
        <span class="gc-kpi">Конец: ${ddmmyy(s.blEnd)} → <b>${ddmmyy(s.curEnd)}</b> ${badge(s.dEnd)}</span>
        ${s.hours0 != null ? `<span class="gc-kpi">План: ${h(s.hours0)} → <b>${h(s.hours1)} ч</b></span>` : ''}
        ${s.spent0 != null ? `<span class="gc-kpi">Списано: ${h(s.spent0)} → <b>${h(s.spent1)} ч</b></span>` : ''}
        <span class="gc-kpi">Задачи: <span class="gc-late">позже ${s.nLater}</span> · <span class="gc-early">раньше ${s.nEarlier}</span> · без сдвига ${s.nSame} · новых ${s.nNew} · убрано ${s.nRemoved}</span>
      </div>
      ${cmp.detailed ? '' : '<div class="gc-warn">⚠ Этот слепок старого формата: в нём только даты задач (без оценок, списаний и исполнителей), поэтому причины сдвига показаны неполно.</div>'}
      <div class="gc-text">${lines.map(l => `<p>${l}</p>`).join('')}</div>
      ${catRows ? `<details open><summary>Причины сдвига (корневые)</summary><table class="gc-table"><tr><th>Причина</th><th>Задач</th><th>Объём</th><th>Повлияла на</th><th>Примеры</th></tr>${catRows}</table>
        <div class="gc-note">«Повлияла на» — сколько задач сдвинулось из-за этой причины напрямую или по цепочке ожидания (фаза стори → очередь исполнителя).</div></details>` : ''}
      <details open><summary>Эпики: куда сдвинулся конец и почему</summary><table class="gc-table"><tr><th>Эпик</th><th>Было</th><th>Стало</th><th>Сдвиг</th><th>Почему</th></tr>${epics}</table></details>
      <details><summary>Исполнители: остаток работы и конец очереди</summary><table class="gc-table"><tr><th>Исполнитель</th><th>Остаток было</th><th>Остаток стало</th><th>Конец было</th><th>Конец стало</th><th>Сдвиг</th></tr>${resRows}</table>
        <div class="gc-note">Остаток на дату слепка и на текущую дату: бэклог — вся оценка, в работе — оценка минус списано.</div></details>
      <details><summary>Топ-15 сдвигов по задачам</summary><table class="gc-table"><tr><th>Задача</th><th>Роль</th><th>Название</th><th>Сдвиг</th><th>Почему</th></tr>${top}</table></details>
      ${removed.length ? `<details><summary>Убраны из плана: ${removed.length}</summary><div class="gc-keys">${removed.map(r => `${jiraLink(r.key)} ${(r.b.summary || '').slice(0, 50)}`).join('<br>')}</div></details>` : ''}
      <div class="gc-note">Сдвиги считаются в рабочих днях по концу задачи. На ганте: пунктир — прошлый план, стрелка — куда сдвинулся конец, бейдж — на сколько. Наведи на бар, чтобы увидеть причину.</div>`;
  }

  return {loadBaselines, compare, panelHtml, fmtDays, ddmm};
})();
