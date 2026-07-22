/* 이차전지 리포트 아카이브 — 인덱스 클라이언트 로직
   /data/reports.json 을 읽어 카드 렌더 + 카테고리 필터링 */

const CATEGORIES = {
  all:            { label: '전체',            emoji: '' },
  'global-policy':{ label: '글로벌 정책·시사', emoji: '🌍' },
  'global-market':{ label: '글로벌 산업·시황', emoji: '📊' },
  'korea-policy': { label: '국내 정책·시사',   emoji: '🇰🇷' },
  'korea-market': { label: '국내 산업·시황',   emoji: '🇰🇷' },
};

const REL = {
  direct:   { label: '🔋 직접', cls: 'badge-rel-direct' },
  indirect: { label: '🔋 간접', cls: 'badge-rel-indirect' },
};

let ALL_REPORTS = [];
let activeCat = 'all';

function catVar(cat) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue('--c-' + cat).trim() || '#444';
}

function renderTabs() {
  const counts = { all: ALL_REPORTS.length };
  for (const r of ALL_REPORTS) counts[r.category] = (counts[r.category] || 0) + 1;

  const tabs = document.getElementById('tabs');
  tabs.innerHTML = '';
  for (const [key, meta] of Object.entries(CATEGORIES)) {
    const n = counts[key] || 0;
    const btn = document.createElement('button');
    btn.className = 'tab' + (key === activeCat ? ' active' : '');
    btn.innerHTML = `${meta.emoji ? meta.emoji + ' ' : ''}${meta.label}` +
                    `<span class="count">${n}</span>`;
    btn.onclick = () => { activeCat = key; renderTabs(); renderCards(); };
    tabs.appendChild(btn);
  }
}

function renderCards() {
  const list = document.getElementById('cards');
  const items = ALL_REPORTS
    .filter(r => activeCat === 'all' || r.category === activeCat)
    .sort((a, b) => (a.date < b.date ? 1 : -1)); // 최신순

  if (!items.length) {
    list.innerHTML = '<div class="empty">해당 카테고리의 리포트가 아직 없습니다.</div>';
    return;
  }

  list.innerHTML = '';
  for (const r of items) {
    const cat = CATEGORIES[r.category] || { label: r.category, emoji: '' };
    const rel = REL[r.relation] || REL.indirect;
    const a = document.createElement('a');
    a.className = 'card';
    a.href = r.url;
    a.style.setProperty('--cat', catVar(r.category));
    a.innerHTML = `
      <div class="card-meta">
        <span class="badge badge-cat">${cat.emoji ? cat.emoji + ' ' : ''}${cat.label}</span>
        <span class="badge ${rel.cls}">${rel.label}</span>
        <span class="badge badge-channel">${escapeHtml(r.channel)}</span>
        <span class="card-date">${r.date}</span>
      </div>
      <div class="card-title">${escapeHtml(r.title)}</div>
      <p class="card-summary">${escapeHtml(r.summary)}</p>`;
    list.appendChild(a);
  }
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function init() {
  try {
    const res = await fetch('../data/reports.json', { cache: 'no-cache' });
    const data = await res.json();
    ALL_REPORTS = Array.isArray(data.reports) ? data.reports : [];
    const stamp = document.getElementById('generated');
    if (stamp && data.generated_at) {
      stamp.textContent = '최근 갱신: ' + data.generated_at.replace('T', ' ').slice(0, 16);
    }
  } catch (e) {
    ALL_REPORTS = [];
    console.error('reports.json 로드 실패', e);
  }
  renderTabs();
  renderCards();
}

document.addEventListener('DOMContentLoaded', init);
