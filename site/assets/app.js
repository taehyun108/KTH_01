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
let CHANNEL_ROSTER = [];    // 설정된 전체 채널명(0건 채널도 칩으로 표시)
// 카테고리는 여러 개를 동시에 켤 수 있는 다중 선택 필터 (비어 있으면 '전체')
let activeCats = new Set();
// 즐겨찾기·숨김은 카테고리 필터와 별개로 동작하는 단독 보기
let activeView = 'all';     // all | fav | hidden
let activeChannel = 'all';  // all | <channel name>
let searchTerm = '';

const load = (k) => { try { return new Set(JSON.parse(localStorage.getItem(k) || '[]')); } catch { return new Set(); } };
const save = (k, s) => localStorage.setItem(k, JSON.stringify([...s]));
let favs = load(LS_FAV);
let hidden = load(LS_HIDE);

/* 즐겨찾기·숨김은 리포트 id 를 브라우저에 저장한다. 그런데 리포트가 영구 삭제되거나
   재생성되며 id(슬러그)가 바뀌면, 저장된 id 는 남고 대응하는 리포트는 사라진다.
   그러면 "숨김 1건"이라고 뜨는데 목록은 비어 있는 상태가 된다.
   → 데이터를 읽은 직후 실제로 존재하지 않는 id 를 걷어내고 저장까지 갱신한다. */
function pruneStaleIds() {
  const live = new Set(ALL.map(r => r.id));
  for (const [key, set] of [[LS_FAV, favs], [LS_HIDE, hidden]]) {
    const stale = [...set].filter(id => !live.has(id));
    if (!stale.length) continue;
    stale.forEach(id => set.delete(id));
    save(key, set);
    console.info(`[정리] 사라진 리포트 ${stale.length}건을 ${key} 에서 제거했습니다.`, stale);
  }
}

/* 화면에 실제로 보여줄 수 있는 건수만 센다(저장된 id 개수가 아니라).
   pruneStaleIds 가 이미 정리하지만, 계산 자체도 데이터 기준으로 두어 두 번 막는다. */
const countLive = (set) => ALL.reduce((n, r) => n + (set.has(r.id) ? 1 : 0), 0);

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
  // 숨긴 리포트는 즐겨찾기 목록에서도 빠지므로(아래 필터와 동일 기준) 그만큼 빼고 센다
  const favVisible = ALL.reduce((n, r) => n + (favs.has(r.id) && !hidden.has(r.id) ? 1 : 0), 0);
  items.push(['fav', `⭐ 즐겨찾기`, favVisible]);
  items.push(['hidden', `🗑 숨김`, countLive(hidden)]);

  const el = document.getElementById('pills');
  el.innerHTML = '';
  for (const [key, label, n] of items) {
    const b = document.createElement('button');
    let on;
    if (key === 'all') on = activeView === 'all' && activeCats.size === 0;
    else if (key === 'fav' || key === 'hidden') on = activeView === key;
    else on = activeView === 'all' && activeCats.has(key);   // 카테고리: 다중 선택

    b.className = 'pill' + (on ? ' active' : '');
    b.innerHTML = `${label}<span class="n">${n}</span>`;
    b.onclick = () => {
      if (key === 'all') {                    // 전체: 카테고리 선택 모두 해제
        activeCats.clear();
        activeView = 'all';
      } else if (key === 'fav' || key === 'hidden') {
        // 즐겨찾기·숨김은 카테고리 필터와 별개(단독 보기) — 다시 누르면 해제
        activeView = activeView === key ? 'all' : key;
        activeCats.clear();
      } else {                                // 카테고리: 켜고 끄기(중복 선택 가능)
        activeView = 'all';
        if (activeCats.has(key)) activeCats.delete(key); else activeCats.add(key);
      }
      render();
    };
    el.appendChild(b);
  }
}

function currentItems() {
  let items = ALL.slice();
  if (activeView === 'hidden') {
    items = items.filter(r => hidden.has(r.id));
  } else if (activeView === 'fav') {
    items = items.filter(r => favs.has(r.id) && !hidden.has(r.id));
  } else {
    items = items.filter(r => !hidden.has(r.id));
    // 선택된 카테고리가 하나라도 있으면 그 카테고리들만 (없으면 전체)
    if (activeCats.size) items = items.filter(r => activeCats.has(r.category));
  }
  if (activeChannel !== 'all') items = items.filter(r => r.channel === activeChannel);
  if (searchTerm) {
    const q = searchTerm.toLowerCase();
    items = items.filter(r =>
      (r.title + ' ' + r.summary + ' ' + r.channel).toLowerCase().includes(q));
  }
  return items.sort((a, b) => (a.date < b.date ? 1 : -1));
}

function renderChannels() {
  const el = document.getElementById('channels');
  if (!el) return;
  const counts = {};
  for (const r of ALL) if (!hidden.has(r.id)) counts[r.channel] = (counts[r.channel] || 0) + 1;
  const total = ALL.filter(r => !hidden.has(r.id)).length;

  // 설정된 전체 채널(로스터) + 데이터에 존재하는 채널의 합집합 → 0건도 표시
  const names = [];
  for (const n of CHANNEL_ROSTER) if (!names.includes(n)) names.push(n);
  for (const n of Object.keys(counts)) if (!names.includes(n)) names.push(n);
  const items = [['all', '전체 채널', total], ...names.map(n => [n, n, counts[n] || 0])];

  el.innerHTML = '';
  for (const [key, label, n] of items) {
    const b = document.createElement('button');
    b.className = 'chip' + (key === activeChannel ? ' active' : '') + (n === 0 && key !== 'all' ? ' empty' : '');
    b.style.setProperty('--tag', key === 'all' ? 'var(--accent-strong)' : tagColor(key));
    b.innerHTML = `${esc(label)}<span class="n">${n}</span>`;
    b.onclick = () => { activeChannel = key; render(); };
    el.appendChild(b);
  }

  // 토글 버튼 라벨: 선택된 채널을 표시
  const toggle = document.getElementById('chan-toggle');
  if (toggle) {
    const sel = activeChannel !== 'all'
      ? ` · <span class="sel">${esc(activeChannel)}</span>` : '';
    toggle.innerHTML = `📺 채널 필터${sel} <span class="caret">▾</span>`;
  }
}

function sectionLabel() {
  let base;
  if (activeView === 'fav') base = '⭐ 즐겨찾기';
  else if (activeView === 'hidden') base = '🗑 숨긴 리포트';
  else if (activeCats.size === 0) base = '전체 리포트';
  else {
    // 선택된 카테고리를 모두 표기 (3개 이상이면 축약)
    const picked = Object.keys(CATEGORIES).filter(k => activeCats.has(k));
    base = picked.length <= 2
      ? picked.map(k => `${CATEGORIES[k].emoji} ${CATEGORIES[k].label}`).join(' · ')
      : `${picked.map(k => CATEGORIES[k].short).slice(0, 2).join(' · ')} 외 ${picked.length - 2}개`;
  }
  if (activeChannel !== 'all') base += ` · ${activeChannel}`;
  return base;
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
          ${isMaster() ? '<button class="icon-btn del" title="영구 삭제 (마스터)">🗑</button>' : ''}
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
    const delBtn = card.querySelector('.del');
    if (delBtn) delBtn.onclick = (e) => { e.preventDefault(); requestDelete(r); };
    list.appendChild(card);
  }
}

// 즐겨찾기 탭에서만 'URL 직접 요약' 도구를 노출
function renderFavTools() {
  const el = document.getElementById('fav-tools');
  if (!el) return;
  if (activeView === 'fav') el.removeAttribute('hidden');
  else el.setAttribute('hidden', '');
}

// 유튜브 URL → 사전 작성된 GitHub 이슈 생성 페이지로 이동 (Actions 워크플로가 요약)
const REPO = 'taehyun108/KTH_01';

// ── 마스터 모드 ─────────────────────────────────────────────
// 주의: 이 비밀번호는 브라우저에 내려가는 값이라 '실수 방지용 잠금'이지 보안장치가 아니에요.
// 실제 삭제 권한은 GitHub 워크플로가 '저장소 소유자가 연 이슈'만 처리하는 것으로 지켜집니다.
const MASTER_PW = '1081';
const LS_MASTER = 'bra_master';
function isMaster() { return sessionStorage.getItem(LS_MASTER) === '1'; }

function toggleMaster() {
  if (isMaster()) {
    sessionStorage.removeItem(LS_MASTER);
    render(); renderMasterBtn();
    return;
  }
  const pw = window.prompt('마스터 비밀번호를 입력하세요');
  if (pw === null) return;
  if (pw.trim() !== MASTER_PW) { window.alert('비밀번호가 올바르지 않습니다.'); return; }
  sessionStorage.setItem(LS_MASTER, '1');
  render(); renderMasterBtn();
}

function renderMasterBtn() {
  const b = document.getElementById('master-btn');
  if (!b) return;
  const on = isMaster();
  b.textContent = on ? '🔓 마스터 해제' : '🔒 마스터';
  b.classList.toggle('on', on);
  b.title = on ? '마스터 모드 켜짐 — 카드에서 🗑로 영구 삭제' : '마스터 모드 켜기';
}

// 영구 삭제 요청 — GitHub 이슈를 열어 워크플로가 실제로 파일을 지우게 한다
function requestDelete(r) {
  if (!isMaster()) return;
  if (!window.confirm(
      `이 리포트를 아카이브에서 영구 삭제할까요?\n\n${r.title}\n\n` +
      '확인을 누르면 GitHub 삭제 요청 페이지가 열립니다.')) return;
  const title = encodeURIComponent('[삭제] ' + r.id);
  const body = encodeURIComponent(
    '아래 리포트를 아카이브에서 삭제해 주세요.\n\n' +
    `- id: ${r.id}\n- 제목: ${r.title}\n- 영상: ${r.video || ''}\n\n` +
    '사유: 내용과 무관한 요약\n');
  window.open(`https://github.com/${REPO}/issues/new?title=${title}&body=${body}`,
              '_blank', 'noopener');
}
const YT_RE = /^(https?:\/\/)?(www\.)?(youtube\.com\/(watch\?v=|shorts\/|embed\/)|youtu\.be\/)[\w-]{6,}/i;

function requestSummary() {
  const input = document.getElementById('yt-url');
  const hint = document.getElementById('yt-hint');
  let url = (input.value || '').trim();
  if (!url) { input.focus(); return; }
  if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
  if (!YT_RE.test(url)) {
    hint.innerHTML = '⚠️ 올바른 유튜브 주소가 아닙니다. 예) https://www.youtube.com/watch?v=...';
    hint.classList.add('err');
    return;
  }
  hint.classList.remove('err');
  const title = encodeURIComponent('[요약] ' + url);
  const body = encodeURIComponent(
    '아래 유튜브 영상을 이차전지 리포트로 요약해 주세요.\n\n' + url + '\n');
  window.open(`https://github.com/${REPO}/issues/new?title=${title}&body=${body}`, '_blank', 'noopener');
  hint.innerHTML = '↗️ GitHub 페이지에서 <b>‘Submit new issue’</b>를 눌러 주세요. ' +
    '제출 후 1~3분 뒤 이 목록에 리포트가 추가됩니다.';
}

function render() { renderStats(); renderPills(); renderChannels(); renderFavTools(); renderCards(); }

async function init() {
  try {
    const res = await fetch('../data/reports.json', { cache: 'no-cache' });
    const data = await res.json();
    ALL = Array.isArray(data.reports) ? data.reports : [];
    CHANNEL_ROSTER = Array.isArray(data.channels) ? data.channels : [];
    pruneStaleIds();
    const stamp = document.getElementById('generated');
    if (stamp && data.generated_at) stamp.textContent = '최근 갱신: ' + data.generated_at.replace('T', ' ').slice(0, 16);
  } catch (e) { ALL = []; console.error('reports.json 로드 실패', e); }

  const search = document.getElementById('search');
  search.addEventListener('input', () => { searchTerm = search.value.trim(); renderCards(); });

  // 마스터 모드 토글
  const mb = document.getElementById('master-btn');
  if (mb) { mb.addEventListener('click', toggleMaster); renderMasterBtn(); }

  // 홈 버튼: 목록 최상단(홈) 상태로 되돌리며 새로고침
  const homeBtn = document.getElementById('home-btn');
  if (homeBtn) {
    homeBtn.addEventListener('click', (e) => {
      e.preventDefault();
      // 캐시된 reports.json 대신 최신 데이터를 받도록 강제 새로고침
      window.location.reload();
    });
  }

  // 즐겨찾기 탭: URL 직접 요약 요청
  const ytBtn = document.getElementById('yt-submit');
  const ytUrl = document.getElementById('yt-url');
  if (ytBtn) ytBtn.addEventListener('click', requestSummary);
  if (ytUrl) ytUrl.addEventListener('keydown', (e) => { if (e.key === 'Enter') requestSummary(); });

  // 채널 필터 접기/펼치기 토글
  const toggle = document.getElementById('chan-toggle');
  const list = document.getElementById('channels');
  if (toggle && list) {
    toggle.addEventListener('click', () => {
      const nowHidden = list.hasAttribute('hidden');
      if (nowHidden) { list.removeAttribute('hidden'); toggle.classList.add('open'); toggle.setAttribute('aria-expanded', 'true'); }
      else { list.setAttribute('hidden', ''); toggle.classList.remove('open'); toggle.setAttribute('aria-expanded', 'false'); }
    });
  }

  render();
}
document.addEventListener('DOMContentLoaded', init);
