/* 이차전지 리포트 아카이브 — 카드 뉴스 인덱스
   /data/reports.json 기반: 헤더 통계 + 검색 + 카테고리 필터 + 즐겨찾기/숨김 */

const CATEGORIES = {
  'macro':        { label: '거시경제',         short: '거시경제',   emoji: '📈' },
  'global-policy':{ label: '글로벌 정책·시사', short: '글로벌정책', emoji: '🌍' },
  'global-market':{ label: '글로벌 산업·시황', short: '글로벌산업', emoji: '📊' },
  'korea-policy': { label: '국내 정책·시사',   short: '국내정책',   emoji: '🇰🇷' },
  'korea-market': { label: '국내 산업·시황',   short: '국내산업',   emoji: '🇰🇷' },
};
const REL = {
  direct:   { label: '🔋 직접', cls: 'badge-rel-direct' },
  indirect: { label: '🔋 간접', cls: 'badge-rel-indirect' },
};
// 채널 태그 색상 팔레트 (이름 해시로 배정)
const TAG_COLORS = ['#0ea5e9','#6366f1','#0891b2','#7c3aed','#ea8a0b','#e11d48','#0d9488','#2563eb'];

const LS_FAV = 'bra_fav', LS_HIDE = 'bra_hidden';

let ALL = [];
let activeFilter = 'all';   // all | <category> | fav | hidden
let searchTerm = '';

const load = (k) => { try { return new Set(JSON.parse(localStorage.getItem(k) || '[]')); } catch { return new Set(); } };
const save = (k, s) => localStorage.setItem(k, JSON.stringify([...s]));
let favs = load(LS_FAV);
let hidden = load(LS_HIDE);

function catVar(cat) {
  return getComputedStyle(document.documentElement).getPropertyValue('--c-' + cat).trim() || '#64748b';
}
function tagColor(name) {
  let h = 0; for (const ch of String(name)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TAG_COLORS[h % TAG_COLORS.length];
}
function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function renderStats() {
  const counts = {};
  for (const r of ALL) if (!hidden.has(r.id)) counts[r.category] = (counts[r.category] || 0) + 1;
  const total = ALL.filter(r => !hidden.has(r.id)).length;
  const el = document.getElementById('stats');
  const parts = Object.entries(CATEGORIES).map(([k, m]) =>
    `<div class="stat"><b>${counts[k] || 0}</b><span>${m.short}</span></div>`);
  parts.push(`<div class="stat"><b>${total}</b><span>전체</span></div>`);
  el.innerHTML = parts.join('');
}

function renderPills() {
  const counts = {};
  for (const r of ALL) if (!hidden.has(r.id)) counts[r.category] = (counts[r.category] || 0) + 1;
  const total = ALL.filter(r => !hidden.has(r.id)).length;

  const items = [['all', `전체`, total]];
  for (const [k, m] of Object.entries(CATEGORIES)) items.push([k, `${m.emoji} ${m.label}`, counts[k] || 0]);
  items.push(['fav', `⭐ 즐겨찾기`, favs.size]);
  items.push(['hidden', `🗑 숨김`, hidden.size]);

  const el = document.getElementById('pills');
  el.innerHTML = '';
  for (const [key, label, n] of items) {
    const b = document.createElement('button');
    b.className = 'pill' + (key === activeFilter ? ' active' : '');
    b.innerHTML = `${label}<span class="n">${n}</span>`;
    b.onclick = () => { activeFilter = key; render(); };
    el.appendChild(b);
  }
}

function currentItems() {
  let items = ALL.slice();
  if (activeFilter === 'hidden') {
    items = items.filter(r => hidden.has(r.id));
  } else if (activeFilter === 'fav') {
    items = items.filter(r => favs.has(r.id) && !hidden.has(r.id));
  } else {
    items = items.filter(r => !hidden.has(r.id));
    if (activeFilter !== 'all') items = items.filter(r => r.category === activeFilter);
  }
  if (searchTerm) {
    const q = searchTerm.toLowerCase();
    items = items.filter(r =>
      (r.title + ' ' + r.summary + ' ' + r.channel).toLowerCase().includes(q));
  }
  return items.sort((a, b) => (a.date < b.date ? 1 : -1));
}

function sectionLabel() {
  if (activeFilter === 'all') return '전체 리포트';
  if (activeFilter === 'fav') return '⭐ 즐겨찾기';
  if (activeFilter === 'hidden') return '🗑 숨긴 리포트';
  const m = CATEGORIES[activeFilter];
  return `${m.emoji} ${m.label}`;
}

function renderCards() {
  const items = currentItems();
  const head = document.getElementById('section-head');
  head.innerHTML = `<span>${sectionLabel()}</span><span class="n">${items.length}</span>`;

  const list = document.getElementById('cards');
  if (!items.length) {
    list.innerHTML = '<div class="empty">해당 조건의 리포트가 없습니다.</div>';
    return;
  }
  list.innerHTML = '';
  for (const r of items) {
    const cat = CATEGORIES[r.category] || { label: r.category, emoji: '' };
    const rel = REL[r.relation] || REL.indirect;
    const isFav = favs.has(r.id);
    const isHidden = hidden.has(r.id);

    const card = document.createElement('article');
    card.className = 'card';
    card.style.setProperty('--cat', catVar(r.category));
    card.innerHTML = `
      <div class="card-top">
        <span class="card-date">${esc(r.date)}</span>
        <div class="card-actions">
          <span class="tag-channel" style="--tag:${tagColor(r.channel)}">${esc(r.channel)}</span>
          <button class="icon-btn fav${isFav ? ' on' : ''}" title="즐겨찾기">${isFav ? '★' : '☆'}</button>
          <button class="icon-btn hide" title="${isHidden ? '숨김 해제' : '숨기기'}">${isHidden ? '↩' : '✕'}</button>
        </div>
      </div>
      <a class="card-body" href="${esc(r.url)}">
        <div class="card-title">${esc(r.title)}</div>
        <p class="card-summary">${esc(r.summary)}</p>
      </a>
      <div class="card-tags">
        <span class="badge badge-cat" style="--cat:${catVar(r.category)}">${cat.emoji ? cat.emoji + ' ' : ''}${cat.label}</span>
        <span class="badge ${rel.cls}">${rel.label}</span>
      </div>`;

    card.querySelector('.fav').onclick = (e) => {
      e.preventDefault();
      if (favs.has(r.id)) favs.delete(r.id); else favs.add(r.id);
      save(LS_FAV, favs); render();
    };
    card.querySelector('.hide').onclick = (e) => {
      e.preventDefault();
      if (hidden.has(r.id)) hidden.delete(r.id); else hidden.add(r.id);
      save(LS_HIDE, hidden); render();
    };
    list.appendChild(card);
  }
}

function render() { renderStats(); renderPills(); renderCards(); }

async function init() {
  try {
    const res = await fetch('../data/reports.json', { cache: 'no-cache' });
    const data = await res.json();
    ALL = Array.isArray(data.reports) ? data.reports : [];
    const stamp = document.getElementById('generated');
    if (stamp && data.generated_at) stamp.textContent = '최근 갱신: ' + data.generated_at.replace('T', ' ').slice(0, 16);
  } catch (e) { ALL = []; console.error('reports.json 로드 실패', e); }

  const search = document.getElementById('search');
  search.addEventListener('input', () => { searchTerm = search.value.trim(); renderCards(); });

  render();
}
document.addEventListener('DOMContentLoaded', init);
