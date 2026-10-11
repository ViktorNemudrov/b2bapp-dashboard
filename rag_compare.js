// Сравнение текущего плана со слепком для мастер-файла RAG (build_rag_master.py).
// Использует ту же логику, что страница Ганта (public/pages/gantt-compare.js),
// чтобы объяснение сдвигов в RAG совпадало с тем, что видно на дашборде.
// node rag_compare.js <data.json> <baselines.json> <baselineId|ts> → JSON в stdout
const fs = require('fs'), vm = require('vm'), path = require('path');
const [dataPath, blPath, blRef] = process.argv.slice(2);
const src = fs.readFileSync(path.join(__dirname, 'public/pages/gantt-compare.js'), 'utf8');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(src + '\nthis.GC = GC;', ctx);
const GC = ctx.GC;

const d = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
const all = JSON.parse(fs.readFileSync(blPath, 'utf8')).baselines || [];
const bl = all.filter(b => b.ts === blRef || b.id === blRef).pop();
if(!bl){ console.error('baseline not found: ' + blRef); process.exit(2); }
const names = {};
(d.ganttV2.resources || []).forEach(r => names[r.id] = r.name || r.id);
const cmp = GC.compare(bl, d.ganttV2, names);

const pick = r => ({key: r.key, type: r.type, state: r.state, dEnd: r.dEnd || 0,
  bEnd: r.b ? r.b.end : null, cEnd: r.c ? r.c.end : null, why: r.why || '',
  root: r.root ? r.root.code : null, summary: (r.c || r.b || {}).summary || ''});
const s = cmp.summary;
const out = {
  baseline: {id: bl.id, ts: bl.ts, label: bl.label},
  sentences: GC.sentence(cmp),
  summary: {blEnd: s.blEnd, curEnd: s.curEnd, dEnd: s.dEnd, hours0: s.hours0, hours1: s.hours1,
    spent0: s.spent0, spent1: s.spent1, nLater: s.nLater, nEarlier: s.nEarlier, nSame: s.nSame,
    nNew: s.nNew, nRemoved: s.nRemoved, resources: s.resources},
  cats: Object.values(s.cats).map(k => ({code: k.code, label: GC.CAT_LABEL[k.code] || k.code, n: k.n,
    hours: Math.round((k.hours || 0) * 10) / 10, impacted: k.impacted, later: k.later, earlier: k.earlier,
    maxShift: k.maxShift, keys: k.keys})),
  items: Object.values(cmp.res).map(pick),
};
process.stdout.write(JSON.stringify(out));
