// shared-nav.js — общая навигация, индикатор свежести и утилиты B2BAPP Dashboard
// Подключается на всех страницах: <div id="sidebar-root"></div> + <script src=".../shared-nav.js"></script> + renderSidebar();
(function(){
'use strict';

const NAV = [
  {group:'Обзор', items:[
    {label:'Главная', icon:'🏠', href:'/index.html'},
    {label:'Статус для руководства', icon:'🧾', href:'/pages/status.html'},
  ]},
  {group:'План', items:[
    {label:'Диаграмма Ганта', icon:'📊', href:'/pages/gantt.html'},
    {label:'Ресурсный план', icon:'👥', href:'/pages/resources.html'},
    {label:'График отпусков', icon:'🏖️', href:'/pages/vacations.html'},
  ]},
  {group:'Аналитика', items:[
    {label:'Реестр рисков', icon:'⚠️', href:'/pages/risks.html'},
    {label:'Реестр допущений', icon:'📌', href:'/pages/assumptions.html'},
  ]},
];
window.NAV = NAV;

// Применяем сохранённое состояние сворачивания СРАЗУ при загрузке скрипта
// (не дожидаясь renderSidebar/DOMContentLoaded), чтобы не было мигания
// развёрнутого сайдбара перед тем, как он схлопнется на уже свёрнутых страницах.
const SIDEBAR_COLLAPSE_KEY = 'b2bapp_sidebar_collapsed';
if(localStorage.getItem(SIDEBAR_COLLAPSE_KEY) === '1'){
  document.body.classList.add('sidebar-hidden');
}

function currentPath(){
  let p = location.pathname;
  if(p===''||p==='/') p='/index.html';
  if(!p.startsWith('/')) p='/'+p;
  return p;
}

function renderSidebar(){
  const mount = document.getElementById('sidebar-root');
  if(!mount) return;
  const cur = currentPath();
  const groupsHtml = NAV.map(g=>`
    <div class="nav-section">${g.group}</div>
    ${g.items.map(it=>{
      const itPath = it.href.split('#')[0];
      const active = itPath===cur;
      return `<a class="nav-link${active?' active':''}" href="${it.href}"><span class="nav-icon">${it.icon}</span><span class="nav-label">${it.label}</span>${it.wip?'<span class="nav-wip" title="Раздел в разработке">в разработке</span>':''}</a>`;
    }).join('')}
  `).join('');
  const nav = document.createElement('nav');
  nav.className = 'sidebar';
  nav.id = 'sidebar';
  nav.innerHTML = `
    <a class="sidebar-logo" href="/index.html" aria-label="B2BAPP — на главную">
      <img src="/assets/logo-dark.png" class="sidebar-logo-img theme-dark-only" alt="">
      <img src="/assets/logo-light.png" class="sidebar-logo-img theme-light-only" alt="">
      <div><div class="sidebar-logo-text">beeline<br>B2BAPP</div></div>
    </a>
    <div class="sidebar-nav">${groupsHtml}</div>
  `;
  mount.replaceWith(nav);

  let burger = document.getElementById('sidebarBurger');
  if(!burger){
    burger = document.createElement('button');
    burger.id = 'sidebarBurger';
    burger.className = 'sidebar-burger';
    burger.type = 'button';
    burger.setAttribute('aria-label','Меню');
    burger.textContent = '☰';
    document.body.appendChild(burger);
  }
  burger.onclick = ()=> document.getElementById('sidebar')?.classList.toggle('open');
  document.addEventListener('click', e=>{
    const sb = document.getElementById('sidebar');
    if(!sb || !sb.classList.contains('open')) return;
    if(sb.contains(e.target) || e.target===burger) return;
    sb.classList.remove('open');
  });

  let collapseBtn = document.getElementById('sidebarCollapseBtn');
  if(!collapseBtn){
    collapseBtn = document.createElement('button');
    collapseBtn.id = 'sidebarCollapseBtn';
    collapseBtn.className = 'sidebar-collapse-btn';
    collapseBtn.type = 'button';
    document.body.appendChild(collapseBtn);
  }
  const syncCollapseBtn = ()=>{
    const hidden = document.body.classList.contains('sidebar-hidden');
    collapseBtn.textContent = hidden ? '▸' : '◂';
    collapseBtn.setAttribute('aria-label', hidden ? 'Развернуть меню' : 'Свернуть меню');
    collapseBtn.title = hidden ? 'Развернуть меню' : 'Свернуть меню';
  };
  syncCollapseBtn();
  collapseBtn.onclick = ()=>{
    document.body.classList.toggle('sidebar-hidden');
    localStorage.setItem(SIDEBAR_COLLAPSE_KEY, document.body.classList.contains('sidebar-hidden') ? '1' : '0');
    syncCollapseBtn();
  };
}
window.renderSidebar = renderSidebar;

// ── jiraLink (C19) ──────────────────────────────────────────────
function jiraLink(key){
  if(!key) return '';
  // draggable="false": браузеры по умолчанию делают <a> перетаскиваемым
  // (drag ссылки/URL) даже без атрибута draggable — это перехватывало
  // кастомный drag&drop строк на странице Гант (если курсор мыши стартовал
  // прямо на этом тексте ключа), не давая сработать dragstart родительской строки.
  return `<a href="https://btask.beeline.ru/browse/${key}" target="_blank" rel="noopener" draggable="false">${key}</a>`;
}
window.jiraLink = jiraLink;

// ── makeSortable (U13) ──────────────────────────────────────────
function makeSortable(table){
  if(!table || table.dataset.sortableInit) return;
  const thead = table.querySelector('thead');
  if(!thead) return;
  table.dataset.sortableInit = '1';
  const ths = Array.from(thead.querySelectorAll('th'));
  ths.forEach((th,idx)=>{
    th.style.cursor = 'pointer';
    th.addEventListener('click', ()=>{
      const tbody = table.querySelector('tbody');
      if(!tbody) return;
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const dir = th.dataset.dir==='asc' ? 'desc' : 'asc';
      ths.forEach(t=>{delete t.dataset.dir; t.classList.remove('sorted-asc','sorted-desc');});
      th.dataset.dir = dir;
      th.classList.add(dir==='asc' ? 'sorted-asc' : 'sorted-desc');
      rows.sort((a,b)=>{
        const av=(a.children[idx]?.textContent||'').trim();
        const bv=(b.children[idx]?.textContent||'').trim();
        const an=parseFloat(av.replace(',','.')), bn=parseFloat(bv.replace(',','.'));
        const bothNumeric = /^-?[\d.,]+%?$/.test(av) && /^-?[\d.,]+%?$/.test(bv) && !isNaN(an) && !isNaN(bn);
        const cmp = bothNumeric ? (an-bn) : av.localeCompare(bv,'ru');
        return dir==='asc' ? cmp : -cmp;
      });
      rows.forEach(r=>tbody.appendChild(r));
    });
  });
}
window.makeSortable = makeSortable;
function makeSortableAll(sel){
  document.querySelectorAll(sel||'.tbl').forEach(makeSortable);
}
window.makeSortableAll = makeSortableAll;

// ── renderFreshness / U7 ─────────────────────────────────────────
function parseDataDate(raw){
  if(!raw) return null;
  try{
    if(/^\d{4}-\d{2}-\d{2}/.test(raw)) return new Date(raw);
    const [dp,tp] = raw.split(' ');
    const [d,m,y] = dp.split('.');
    const [hh,mm] = (tp||'00:00').split(':');
    const dt = new Date(+y,+m-1,+d,+hh||0,+mm||0);
    return isNaN(dt) ? null : dt;
  }catch{ return null; }
}
function renderFreshness(refreshedAt, fallback){
  const dt = parseDataDate(refreshedAt) || parseDataDate(fallback);
  if(!dt) return '<span class="freshness freshness-gray">Нет данных об обновлении</span>';
  const days = Math.floor((Date.now()-dt.getTime())/86400000);
  const cls = days<=3 ? 'freshness-ok' : days<=7 ? 'freshness-warn' : 'freshness-err';
  const dd = String(dt.getDate()).padStart(2,'0'), mo = String(dt.getMonth()+1).padStart(2,'0');
  const hh = String(dt.getHours()).padStart(2,'0'), mi = String(dt.getMinutes()).padStart(2,'0');
  return `<span class="freshness ${cls}">Данные актуальны на ${dd}.${mo}.${String(dt.getFullYear()).slice(2)} ${hh}:${mi}</span>`;
}
window.renderFreshness = renderFreshness;
// Единый формат дат на сайте — дд.мм.гг (Виктор 26.10.2026). Принимает
// ISO «2026-10-26», «2026-10-26T18:44…», «26.10.2026» или Date.
// Локальная дата YYYY-MM-DD (toISOString даёт UTC — до 03:00 МСК это «вчера»).
function localISO(d){ return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0'); }
function fmtDate(v){
  if(!v) return '—';
  if(v instanceof Date) return isNaN(v)?'—':`${String(v.getDate()).padStart(2,'0')}.${String(v.getMonth()+1).padStart(2,'0')}.${String(v.getFullYear()).slice(2)}`;
  const s=String(v);
  let m=s.match(/^(\d{4})-(\d{2})-(\d{2})/); if(m) return `${m[3]}.${m[2]}.${m[1].slice(2)}`;
  m=s.match(/^(\d{2})\.(\d{2})\.(\d{4})/); if(m) return `${m[1]}.${m[2]}.${m[3].slice(2)}`;
  return s;
}
function fmtDateTime(v){
  if(!v) return '—';
  const m=String(v).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
  return m?`${m[3]}.${m[2]}.${m[1].slice(2)} ${m[4]}:${m[5]}`:fmtDate(v);
}
window.fmtDate = fmtDate; window.fmtDateTime = fmtDateTime;
window.localISO = localISO;
// Метка «устарело» для ручных блоков (статус трека ВП от Cowork, «Команда
// проекта» из Confluence): пусто, пока данным не больше maxDays дней.
function staleBadge(raw, maxDays, what){
  const dt = parseDataDate(raw);
  if(!dt) return '';
  const days = Math.floor((Date.now()-dt.getTime())/86400000);
  if(days <= maxDays) return '';
  return ` <span style="display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;background:rgba(230,162,60,.18);color:#E6A23C;border:1px solid rgba(230,162,60,.5)" title="Последнее обновление ${fmtDate(dt)} — ${days} дн. назад">⚠ ${what||'данные'} устарели: ${days} дн.</span>`;
}
window.staleBadge = staleBadge;

// Текущий спринт — одно правило на весь сайт и в build_dashboard.py (sprint_index):
// пока активный в Jira спринт не кончился по календарю, текущий — он; иначе
// граничный день отдаём уходящему спринту (03.11 — ещё Спринт 4, 04.11 — Спринт 5).
// Виктор 03.11.2026: «старый спринт 4 ещё идёт, а 5 ещё не начат».
function currentSprintN(sprints, today){
  today = today || localISO(new Date());
  const sp = sprints || [];
  const ja = sp.find(s => (s.jiraState||'').toUpperCase()==='ACTIVE' && s.start<=today && today<=s.end);
  if(ja) return ja.n;
  const started = sp.filter(s => s.start < today);
  return started.length ? started[started.length-1].n : (sp[0] ? sp[0].n : 0);
}
// Состояние спринта на сегодня (а не на момент сборки): closed / active / future.
function sprintStateNow(s, curN){ return s.n < curN ? 'closed' : s.n === curN ? 'active' : 'future'; }
// Вызывать сразу после загрузки data.json: состояния спринтов — на сегодня по правилу выше.
function normalizeSprints(d){
  const sp = d && d.ganttV2 && d.ganttV2.sprints;
  if(!sp || !sp.length) return d;
  const cur = currentSprintN(sp);
  sp.forEach(s => { s.state = sprintStateNow(s, cur); });
  return d;
}
window.currentSprintN = currentSprintN; window.sprintStateNow = sprintStateNow; window.normalizeSprints = normalizeSprints;

// Группы статусов — одна палитра на весь сайт (цвета — --st-* в shared.css).
const STATUS_GROUPS = {
  done:    {label:'Готово',          color:'#2ECC71', css:'st-done',    jira:['Завершена','Waiting for release','Done','Закрыта']},
  test:    {label:'На тестировании', color:'#3D8BFD', css:'st-test',    jira:['Ready for testing','Тестирование','Review ready']},
  wip:     {label:'В работе',        color:'#E2B46C', css:'st-wip',     jira:['Разработка','В работе','Анализ','Development','In Progress']},
  ready:   {label:'Запланировано',   color:'#8FA3BF', css:'st-ready',   jira:['Ready for DEV','Запланирована']},  // проанализирована, ждёт разработки
  backlog: {label:'Бэклог',          color:'#5F6B7A', css:'st-backlog', jira:['Бэклог','Backlog']},
  hold:    {label:'На паузе',        color:'#A569BD', css:'st-hold',    jira:['Удержание','Hold']},
};
const STATUS_ORDER = ['done','test','wip','ready','backlog','hold'];
const _ST_BY_NAME = {};
Object.entries(STATUS_GROUPS).forEach(([g,v]) => v.jira.forEach(n => _ST_BY_NAME[n.toLowerCase()] = g));
// Статус Jira (у задач) или category билдера (у стори/эпиков/сценариев) → группа.
function statusGroup(status, category){
  const g = _ST_BY_NAME[String(status||'').toLowerCase()];
  if(g) return g;
  return category==='done' ? 'done' : category==='in_progress' ? 'wip' : 'backlog';
}
function statusBadge(status, category){
  const g = STATUS_GROUPS[statusGroup(status, category)];
  return `<span class="st-badge ${g.css}" title="${g.label}">${status || g.label}</span>`;
}
// Порядок STATUS_ORDER — от завершённого к не начатому (так же идут сегменты полос).
// arrows=true — легенда цепочкой со стрелками, чтобы порядок читался сразу.
function statusLegendHtml(arrows){
  const item = g => `<span><span class="sw" style="background:${STATUS_GROUPS[g].color}"></span>${STATUS_GROUPS[g].label}</span>`;
  if(!arrows) return STATUS_ORDER.map(item).join('');
  const chain = STATUS_ORDER.filter(g => g!=='hold');
  return chain.map(item).join('<span style="opacity:.6">←</span>') + '<span style="margin-left:8px">отдельно:</span>' + item('hold');
}
window.STATUS_GROUPS = STATUS_GROUPS; window.STATUS_ORDER = STATUS_ORDER;
window.statusGroup = statusGroup; window.statusBadge = statusBadge; window.statusLegendHtml = statusLegendHtml;
// ── Автоссылки (Виктор 09.11.2026: «все ссылки на задачи и страницы Confluence — кликабельные») ──
// Любой текст на странице (статичный и отрисованный из data.json): ключ Jira (B2BAPP-1340,
// PFC-1271, B2BAPP-1340/1341) → btask, id страницы Confluence (2577970643, PRODOM/2681750315)
// → bwiki, голый URL → ссылка. Уже существующие <a>, svg, поля ввода и [data-nolink] не трогаем.
// Работает через MutationObserver — страницам ничего вызывать не нужно.
const JIRA_URL = 'https://btask.beeline.ru/browse/', BWIKI = 'https://bwiki.beeline.ru';
const NOT_JIRA = new Set(['UTF','ISO','SHA','TLS','HTTP','HTTPS','COVID','RFC','GOST','IEC','EN','PDF','TCP','UDP','SSL','API','ID']);
const LINK_RE = /(https?:\/\/[^\s<>"«»]+)|\b([A-Z][A-Z0-9]{1,11})-(\d{1,6})((?:\/\d{1,6})*)\b|(?:\b([A-Z][A-Z0-9]{1,11})\/)?\b([12]\d{9})\b/g;
const LINK_SKIP = 'a,script,style,textarea,input,select,option,button,svg,code,[data-nolink],.auth-gate-overlay';
function linkA(href, text){ const a=document.createElement('a'); a.href=href; a.target='_blank'; a.rel='noopener'; a.className='autolink'; a.textContent=text; return a; }
function linkifyTextNode(node){
  const s = node.nodeValue; LINK_RE.lastIndex = 0;
  if(!LINK_RE.test(s)) return; LINK_RE.lastIndex = 0;
  const frag = document.createDocumentFragment(); let last = 0, m, changed = false;
  while((m = LINK_RE.exec(s))){
    let parts = null;
    if(m[1]){ const url = m[1].replace(/[.,;:!?)\]]+$/,''); parts = [linkA(url, url)]; LINK_RE.lastIndex = m.index + url.length; m[0] = url; }
    else if(m[2]){
      if(NOT_JIRA.has(m[2])) continue;
      parts = [linkA(JIRA_URL+m[2]+'-'+m[3], m[2]+'-'+m[3])];
      (m[4]||'').split('/').filter(Boolean).forEach(n => parts.push(document.createTextNode('/'), linkA(JIRA_URL+m[2]+'-'+n, n)));
    }
    else if(m[6]){ parts = [linkA(m[5] ? `${BWIKI}/spaces/${m[5]}/pages/${m[6]}` : `${BWIKI}/pages/viewpage.action?pageId=${m[6]}`, m[0])]; }
    if(!parts) continue;
    frag.appendChild(document.createTextNode(s.slice(last, m.index))); parts.forEach(p => frag.appendChild(p));
    last = m.index + m[0].length; changed = true;
  }
  if(!changed) return;
  frag.appendChild(document.createTextNode(s.slice(last)));
  node.parentNode.replaceChild(frag, node);
}
function linkifyIn(root){
  if(!root || root.nodeType === 3){ if(root && root.parentElement && !root.parentElement.closest(LINK_SKIP)) linkifyTextNode(root); return; }
  if(root.nodeType !== 1 || root.closest(LINK_SKIP)) return;
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {acceptNode: n => n.parentElement && !n.parentElement.closest(LINK_SKIP) && /[A-Z]-\d|\d{10}|https?:/.test(n.nodeValue) ? 1 : 3});
  const list = []; while(w.nextNode()) list.push(w.currentNode);
  list.forEach(linkifyTextNode);
}
window.linkifyIn = linkifyIn;
function startAutoLinks(){
  linkifyIn(document.body);
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(linkifyIn))).observe(document.body, {childList:true, subtree:true});
}
if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', startAutoLinks); else startAutoLinks();

function mountFreshness(elId, refreshedAt, fallback){
  const el = document.getElementById(elId);
  if(el) el.innerHTML = renderFreshness(refreshedAt, fallback);
}
window.mountFreshness = mountFreshness;

// ── renderEmptyState ──────────────────────────────────────────────
function renderEmptyState(msg){
  return `<div class="empty">${msg || 'Нет данных, запустите обновление'}</div>`;
}
window.renderEmptyState = renderEmptyState;

// ── showFetchError: главный fetch data.json на странице не отвечает.catch() —
// без этого страница молча зависает на "Загрузка..." без объяснения причины ──
function showFetchError(err){
  console.error('data.json fetch failed:', err);
  const content = document.querySelector('.content');
  if(!content) return;
  const banner = document.createElement('div');
  banner.className = 'empty';
  banner.style.cssText = 'margin-bottom:14px;border-color:#e74c3c;color:#e74c3c';
  banner.textContent = 'Не удалось загрузить данные. Проверьте соединение и обновите страницу.';
  content.prepend(banner);
}
window.showFetchError = showFetchError;

// ── Theme (для подстраниц, у которых своего JS темы нет) ─────────
function applyTheme(theme){
  if(theme==='light') document.body.classList.add('light-theme');
  else document.body.classList.remove('light-theme');
  const btn = document.getElementById('themeBtn');
  if(btn) btn.textContent = theme==='light' ? '☀️' : '🌙';
}
window.applyTheme = applyTheme;
function detectSystemTheme(){
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}
function toggleTheme(){
  const cur = document.body.classList.contains('light-theme') ? 'light' : 'dark';
  const next = cur==='light' ? 'dark' : 'light';
  sessionStorage.setItem('b2bapp_theme', next);
  applyTheme(next);
}
window.toggleTheme = toggleTheme;
function initTheme(){
  const saved = sessionStorage.getItem('b2bapp_theme');
  applyTheme(saved || detectSystemTheme());
  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', e=>{
    if(!sessionStorage.getItem('b2bapp_theme')) applyTheme(e.matches ? 'light' : 'dark');
  });
}
window.initTheme = initTheme;

// ── AUTH GATE ─────────────────────────────────────────────────────
// Client-side password gate: hides page content behind a full-screen prompt
// until the correct password is entered (once per browser tab session).
// NOTE: this does not protect data.json itself — the file is still fetchable
// directly by URL. Real protection would need Vercel-level access control.
const AUTH_HASH = 'b2923ea2a38d0dae65ce2975b473add6aa82'; // sha256("10122026").slice(0,36)
async function hashPass(p){
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(p));
  return Array.from(new Uint8Array(buf)).map(b=>b.toString(16).padStart(2,'0')).join('').slice(0,36);
}
function checkAuth(){
  return new Promise(resolve=>{
    if(sessionStorage.getItem('b2bapp_auth')==='1'){ resolve(); return; }
    // Локальный предпросмотр (python -m http.server из public/) — без пароля:
    // Claude Code проверяет вёрстку до/после пуша (Виктор 09.11.2026). На проде гейт как был.
    if(['localhost','127.0.0.1'].includes(location.hostname)){ resolve(); return; }
    document.body.classList.add('auth-locked');
    const overlay = document.createElement('div');
    overlay.className = 'auth-gate-overlay';
    overlay.innerHTML = `<div class="auth-card">
      <div class="auth-title">B2BAPP Dashboard</div>
      <div class="auth-sub">Введите пароль для доступа</div>
      <input type="password" class="auth-input" id="authPassInput" placeholder="Пароль">
      <button class="auth-btn" id="authSubmitBtn">Войти</button>
      <div class="auth-err" id="authErr"></div>
    </div>`;
    document.body.appendChild(overlay);
    const input = document.getElementById('authPassInput');
    const err = document.getElementById('authErr');
    async function tryLogin(){
      const h = await hashPass(input.value);
      if(h===AUTH_HASH){
        sessionStorage.setItem('b2bapp_auth','1');
        overlay.remove();
        document.body.classList.remove('auth-locked');
        resolve();
      } else {
        err.textContent = 'Неверный пароль';
        input.value='';
        input.focus();
      }
    }
    document.getElementById('authSubmitBtn').onclick = tryLogin;
    input.addEventListener('keydown', e=>{ if(e.key==='Enter') tryLogin(); });
    setTimeout(()=>input.focus(), 0);
  });
}
window.checkAuth = checkAuth;
window.AUTH_READY = checkAuth();

})();
