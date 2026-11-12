// Выгрузка Jira для дашборда — вставить в консоль (или javascript_tool) на залогиненной
// вкладке https://btask.beeline.ru. Только чтение. Работает в фоне (дольше 45 с):
// результат в window.__FULL, ошибка в window.__FERR; затем dl() скачивает два файла:
//   jira_full_dump.json — весь проект (для build_audit.py): + rem (остаток), linkedBy
//     (кто последним менял привязку задачи без рабочей стори), vacatedBy (кто отправил
//     задачу в вакантные — переименовал в «Вакантная» / перенёс в эпик B2BAPP-135);
//   jira_dump.json — 10 MVP-эпиков, их стори и задачи с оценкой (для build_dashboard.py).
window.__FULL = null; window.__FERR = null;
(async () => { try {
  const EPIC_KEYS = ['B2BAPP-134','B2BAPP-21','B2BAPP-491','B2BAPP-27','B2BAPP-22','B2BAPP-1242','B2BAPP-484','B2BAPP-465','B2BAPP-25','B2BAPP-1241'];
  const F = 'summary,status,issuetype,customfield_10901,customfield_18100,customfield_10905,timetracking,labels,issuelinks,created,resolutiondate,updated,assignee';
  let all = [], s = 0;
  while (true) {
    const j = await (await fetch('/rest/api/2/search?jql=' + encodeURIComponent('project=B2BAPP AND issuetype in (10500,10600,3,20600) ORDER BY key DESC') + '&maxResults=200&startAt=' + s + '&fields=' + F)).json();
    all = all.concat(j.issues); s += j.issues.length;
    if (!j.issues.length || s >= j.total) break;
  }
  const d10 = x => x ? String(x).slice(0, 10) : null;
  const parseSp = arr => (arr || []).map(x => {
    if (typeof x === 'object') return {id: x.id, name: x.name, state: x.state, startDate: d10(x.startDate), endDate: d10(x.endDate), completeDate: d10(x.completeDate)};
    const g = k => { const m = String(x).match(new RegExp(k + '=([^,\\]]*)')); return m && m[1] !== '<null>' ? m[1] : null; };
    return {id: +g('id'), name: g('name'), state: g('state'), startDate: d10(g('startDate')), endDate: d10(g('endDate')), completeDate: d10(g('completeDate'))};
  });
  const nm = a => a ? a.displayName.trim().split(/\s+/).slice(0, 2).join(' ') : null;
  const vac = new Set(all.filter(i => /акантн/.test(i.fields.summary)).map(i => i.key));
  const full = all.map(i => { const f = i.fields, tt = f.timetracking || {}; return {
    key: i.key, type: f.issuetype.id, summary: f.summary, status: f.status.name, epic: f.customfield_10901 || null,
    start: f.customfield_18100 || null, resolved: d10(f.resolutiondate), created: d10(f.created),
    est: tt.originalEstimateSeconds || 0, spent: tt.timeSpentSeconds || 0, rem: tt.remainingEstimateSeconds ?? null,
    labels: f.labels || [], assignee: nm(f.assignee), sprints: parseSp(f.customfield_10905).map(({completeDate, ...r}) => r),
    links: (f.issuelinks || []).map(l => ({type: l.type.name, in: l.inwardIssue ? l.inwardIssue.key : null, out: l.outwardIssue ? l.outwardIssue.key : null,
      inType: l.inwardIssue ? l.inwardIssue.fields.issuetype.id : null, outType: l.outwardIssue ? l.outwardIssue.fields.issuetype.id : null}))}; });
  const need = full.filter(t => (t.type === '3' || t.type === '20600') && !/акантн/.test(t.summary) && (t.epic === 'B2BAPP-135'
    || !t.links.some(l => l.type === 'Part' && l.in && l.inType === '10600' && !vac.has(l.in)) || t.links.some(l => l.type === 'Part' && vac.has(l.in))));
  for (const t of need) {
    const h = ((await (await fetch('/rest/api/2/issue/' + t.key + '?fields=summary&expand=changelog')).json()).changelog.histories || []);
    const lk = h.filter(x => x.items.some(i => ['Link', 'Epic Link'].includes(i.field))).pop();
    const vc = h.filter(x => x.items.some(i => (i.field === 'summary' && /акантн/.test(i.toString || '')) || (i.field === 'Epic Link' && i.toString === 'B2BAPP-135'))).pop();
    if (lk) t.linkedBy = nm(lk.author);
    if (vc) t.vacatedBy = nm(vc.author);
  }
  const bs = await (await fetch('/rest/agile/1.0/board/23111/sprint?maxResults=100')).json();
  const sprints = (bs.values || []).map(x => ({id: x.id, name: x.name, state: (x.state || '').toUpperCase(), startDate: d10(x.startDate), endDate: d10(x.endDate), completeDate: d10(x.completeDate)}));
  const now = new Date().toISOString();
  const raw = i => { const f = i.fields; return {key: i.key, fields: {
    issuetype: {id: f.issuetype.id, name: f.issuetype.name}, summary: f.summary, status: {name: f.status.name},
    created: d10(f.created), resolutiondate: d10(f.resolutiondate), updated: d10(f.updated), labels: f.labels || [],
    timetracking: f.timetracking && f.timetracking.originalEstimateSeconds != null ? {originalEstimateSeconds: f.timetracking.originalEstimateSeconds, timeSpentSeconds: f.timetracking.timeSpentSeconds || 0} : {},
    customfield_10901: f.customfield_10901 || null, customfield_18100: f.customfield_18100 || null, sprints: parseSp(f.customfield_10905),
    issuelinks: (f.issuelinks || []).map(l => ({type: {name: l.type.name, inward: l.type.inward}, ...(l.inwardIssue ? {inwardIssue: {key: l.inwardIssue.key}} : {}), ...(l.outwardIssue ? {outwardIssue: {key: l.outwardIssue.key}} : {})})),
    assignee: f.assignee ? {displayName: nm(f.assignee)} : null}}; };
  const ep = all.filter(i => i.fields.issuetype.id === '10500' && EPIC_KEYS.includes(i.key));
  const st = all.filter(i => i.fields.issuetype.id === '10600' && EPIC_KEYS.includes(i.fields.customfield_10901));
  const tk = all.filter(i => ['3', '20600'].includes(i.fields.issuetype.id) && EPIC_KEYS.includes(i.fields.customfield_10901) && (i.fields.timetracking || {}).originalEstimateSeconds > 0);
  window.__FULL = {
    full: JSON.stringify({collectedAt: now, jql: 'project=B2BAPP AND issuetype in (10500,10600,3,20600)', total: full.length, issues: full}),
    gd: JSON.stringify({_meta: {collectedAt: now, source: 'Jira B2BAPP REST', epics: ep.length, stories: st.length, tasks: tk.length}, sprints, issues: [...ep, ...st, ...tk].map(raw)}),
    n: [full.length, ep.length, st.length, tk.length, need.length, sprints.length]};
} catch (e) { window.__FERR = String(e.stack || e); } })();

function dl(s, n) { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([s], {type: 'application/json'})); a.download = n; document.body.appendChild(a); a.click(); a.remove(); }
// когда window.__FULL готов: dl(window.__FULL.full, 'jira_full_dump.json'); dl(window.__FULL.gd, 'jira_dump.json');
