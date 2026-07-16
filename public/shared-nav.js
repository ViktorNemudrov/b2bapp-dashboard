// shared-nav.js — общая навигация, индикатор свежести и утилиты B2BAPP Dashboard
// Подключается на всех страницах: <div id="sidebar-root"></div> + <script src=".../shared-nav.js"></script> + renderSidebar();
(function(){
'use strict';

const NAV = [
  {group:'Обзор', items:[
    {label:'Главная', icon:'🏠', href:'/index.html'},
    {label:'Executive Summary', icon:'📋', href:'/index.html#s-exec'},
  ]},
  {group:'План', items:[
    {label:'Диаграмма Ганта', icon:'📊', href:'/pages/gantt.html'},
    {label:'Ресурсный план', icon:'👥', href:'/pages/resources.html'},
    {label:'MVP по кварталам', icon:'🏆', href:'/pages/mvp.html'},
    {label:'Скоуп MVP', icon:'📅', href:'/pages/scope_dec.html'},
  ]},
  {group:'Аналитика', items:[
    {label:'USM', icon:'🗺️', href:'/pages/usm.html'},
    {label:'Реестр рисков', icon:'⚠️', href:'/pages/risks.html'},
    {label:'Реестр допущений', icon:'📌', href:'/pages/assumptions.html'},
    {label:'Открытые вопросы', icon:'❓', href:'/pages/questions.html'},
    {label:'Внешние зависимости', icon:'🔗', href:'/pages/dependencies.html'},
    {label:'Стейкхолдеры', icon:'🤝', href:'/pages/stakeholders.html'},
    {label:'Критерии приёмки', icon:'✅', href:'/pages/acceptance.html'},
    {label:'Глоссарий', icon:'📖', href:'/pages/glossary.html'},
    {label:'ОКР', icon:'🎯', href:'/pages/okr.html'},
  ]},
];
window.NAV = NAV;

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
      return `<a class="nav-link${active?' active':''}" href="${it.href}"><span class="nav-icon">${it.icon}</span><span class="nav-label">${it.label}</span></a>`;
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
}
window.renderSidebar = renderSidebar;

// ── jiraLink (C19) ──────────────────────────────────────────────
function jiraLink(key){
  if(!key) return '';
  return `<a href="https://btask.beeline.ru/browse/${key}" target="_blank" rel="noopener">${key}</a>`;
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
  return `<span class="freshness ${cls}">Данные актуальны на ${dd}.${mo}.${dt.getFullYear()} ${hh}:${mi}</span>`;
}
window.renderFreshness = renderFreshness;
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

})();
