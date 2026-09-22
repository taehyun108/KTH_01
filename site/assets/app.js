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
  // 배터리 언급은 없지만 산업 환경으로서 의미가 있는 글.
  // 억지로 배터리를 갖다 붙이는 대신 '산업'이라고 정직하게 표시한다.
  context:  { label: '🏭 산업', cls: 'badge-rel-context' },
};
// 채널 태그 색상 팔레트 (이름 해시로 배정)
const TAG_COLORS = ['#0ea5e9','#6366f1','#0891b2','#7c3aed','#ea8a0b','#e11d48','#0d9488','#2563eb'];

const LS_FAV = 'bra_fav', LS_HIDE = 'bra_hidden';

// 한 페이지에 보여 줄 카드 수. 예전에는 걸러진 리포트를 전부 한 번에 그렸는데,
// 건수가 250개를 넘어가면서 목록이 끝없이 늘어졌다. 페이지로 끊어서 보여 준다.
const PER_PAGE = 15;
let page = 1;

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

/* 카테고리 색은 CSS 변수에서 읽는데, getComputedStyle 은 브라우저에 스타일 계산을
   강제한다. 카드마다 두 번씩 부르고 있었다(15장이면 30번). 값이 바뀌지 않으니 한 번만 읽는다. */
const _catVarCache = new Map();
function catVar(cat) {
  let v = _catVarCache.get(cat);
  if (v === undefined) {
    v = getComputedStyle(document.documentElement).getPropertyValue('--c-' + cat).trim() || '#64748b';
    _catVarCache.set(cat, v);
  }
  return v;
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
      resetPage();
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
  return items;   // 정렬은 불러올 때 한 번만 한다 (아래 init 참고)
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
    b.onclick = () => { activeChannel = key; resetPage(); render(); };
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

/* 페이지 번호 목록을 만든다. 페이지가 많아지면 가운데만 보여 주고 나머지는 '…' 로 접는다.
   예) 현재 7쪽 / 전체 20쪽 → 1 … 5 6 7 8 9 … 20 */
function pageWindow(cur, total) {
  const out = [];
  const push = (v) => { if (out[out.length - 1] !== v) out.push(v); };
  push(1);
  if (cur - 2 > 2) push('…');
  for (let i = Math.max(2, cur - 2); i <= Math.min(total - 1, cur + 2); i++) push(i);
  if (cur + 2 < total - 1) push('…');
  if (total > 1) push(total);
  return out;
}

function gotoPage(p, total) {
  page = Math.min(Math.max(1, p), Math.max(1, total));
  syncPageParam();
  renderCards();
  // 새 페이지의 첫 카드가 보이도록 목록 머리로 올린다(헤더에 가리지 않게 여유를 둔다)
  const head = document.getElementById('section-head');
  if (head) {
    const y = head.getBoundingClientRect().top + window.scrollY - 12;
    window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
  }
}

function renderPager(totalItems) {
  const el = document.getElementById('pager');
  if (!el) return;
  const total = Math.max(1, Math.ceil(totalItems / PER_PAGE));
  if (total <= 1) { el.innerHTML = ''; el.setAttribute('hidden', ''); return; }
  el.removeAttribute('hidden');
  el.innerHTML = '';

  const btn = (label, opts = {}) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'page-btn' + (opts.active ? ' active' : '') + (opts.gap ? ' gap' : '');
    b.textContent = label;
    if (opts.gap) { b.disabled = true; b.setAttribute('aria-hidden', 'true'); }
    if (opts.disabled) b.disabled = true;
    if (opts.label) b.setAttribute('aria-label', opts.label);
    if (opts.active) b.setAttribute('aria-current', 'page');
    if (opts.go != null) b.onclick = () => gotoPage(opts.go, total);
    return b;
  };

  el.appendChild(btn('‹', { go: page - 1, disabled: page === 1, label: '이전 페이지' }));
  for (const v of pageWindow(page, total)) {
    if (v === '…') { el.appendChild(btn('…', { gap: true })); continue; }
    el.appendChild(btn(String(v), { go: v, active: v === page, label: `${v}페이지` }));
  }
  el.appendChild(btn('›', { go: page + 1, disabled: page === total, label: '다음 페이지' }));

  const info = document.createElement('span');
  info.className = 'page-info';
  info.textContent = `${page} / ${total} 페이지`;
  el.appendChild(info);
}

function renderCards() {
  const items = currentItems();
  const total = Math.max(1, Math.ceil(items.length / PER_PAGE));
  // 필터·숨김으로 항목이 줄어 현재 페이지가 사라졌으면 마지막 페이지로 당겨 온다
  if (page > total) { page = total; syncPageParam(); }
  if (page < 1) page = 1;

  const head = document.getElementById('section-head');
  const from = items.length ? (page - 1) * PER_PAGE + 1 : 0;
  const to = Math.min(page * PER_PAGE, items.length);
  head.innerHTML = `<span>${sectionLabel()}</span><span class="n">${items.length}</span>` +
    (items.length > PER_PAGE ? `<span class="range">${from}–${to}번째</span>` : '');

  const list = document.getElementById('cards');
  if (!items.length) {
    list.innerHTML = '<div class="empty">해당 조건의 리포트가 없습니다.</div>';
    renderPager(0);
    return;
  }
  list.innerHTML = '';
  for (const r of items.slice((page - 1) * PER_PAGE, page * PER_PAGE)) {
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
          ${isMaster() ? '<button class="icon-btn tg" title="텔레그램으로 전문 보내기 (마스터)">📨</button>' : ''}
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

    // 📨 는 마스터 모드에서만 그려진다 — 없을 때 onclick 을 걸면 목록이 통째로 깨진다
    const tgBtn = card.querySelector('.tg');
    if (tgBtn) tgBtn.onclick = (e) => { e.preventDefault(); requestSend(r, e.currentTarget); };
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
  renderPager(items.length);
}

/* 새로고침·뒤로가기에도 보던 페이지가 유지되도록 주소에 ?p= 로 남긴다.
   1쪽이면 지저분하니 아예 뺀다. */
function syncPageParam() {
  const url = new URL(window.location.href);
  if (page > 1) url.searchParams.set('p', String(page));
  else url.searchParams.delete('p');
  history.replaceState(null, '', url);
}

// 필터·검색이 바뀌면 보던 페이지 번호는 의미가 없어진다 — 1쪽부터 다시 본다
function resetPage() { page = 1; syncPageParam(); }

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
  if (b) {
    const on = isMaster();
    b.textContent = on ? '🔓 마스터 해제' : '🔒 마스터';
    b.classList.toggle('on', on);
    b.title = on ? '마스터 모드 켜짐 — 카드에서 🗑로 영구 삭제' : '마스터 모드 켜기';
  }
  const t = document.getElementById('gh-token-btn');
  if (t) {
    const has = !!ghToken();
    t.textContent = has ? '🔑 토큰 등록됨' : '🔑 토큰';
    t.classList.toggle('on', has);
    t.title = has
      ? 'GitHub 토큰이 저장돼 있습니다 — URL 등록·텔레그램 전송이 로그인 없이 바로 처리됩니다. 눌러서 바꾸거나 지울 수 있습니다'
      : 'GitHub 토큰을 저장하면 URL 등록·텔레그램 전송이 로그인 없이 바로 처리됩니다 (마스터 모드 필요)';
  }
  // 즐겨찾기 탭의 안내 문구 — 토큰 유무에 따라 실제로 벌어질 일이 다르다.
  // requestSummary() 가 진행 중에 이 자리를 덮어쓰므로, 여기서는 '아직 아무것도
  // 안 눌렀을 때'의 기본 안내만 맞춘다.
  const ytHint = document.getElementById('yt-hint');
  if (ytHint) {
    ytHint.classList.remove('err');
    ytHint.innerHTML = ghToken()
      ? '✅ GitHub 토큰이 저장돼 있어 <b>로그인 없이 바로</b> 처리됩니다. 제출 후 1~3분쯤 걸릴 수 있어요.'
      : '제출하면 GitHub 페이지가 열립니다 — <b>‘Submit new issue’</b>를 누르면 ' +
        '1~3분 뒤 요약 리포트가 아카이브에 추가됩니다. (GitHub 로그인 필요)';
  }
}

// ── GitHub 토큰으로 로그인 없이 바로 실행 ────────────────────────────
// 이 브라우저에만 저장된다(다른 사람 브라우저에는 없으니 그 사람은 예전처럼
// 로그인해서 직접 제출해야 한다). 토큰이 있으면 '즐겨찾기 URL 등록'과 카드의
// 텔레그램 전송이 GitHub 새 이슈 페이지·로그인 화면 없이 API 로 바로 열리고,
// 워크플로가 끝날 때까지 기다렸다가 결과를 그 자리에서 보여 준다.
//
// 실제 처리 권한은 지금과 똑같이 워크플로가 지킨다 — 세 워크플로(summarize-url·
// send-report·delete-report) 모두 "이슈 작성자 == 저장소 소유자"만 처리한다.
// API 로 이슈를 만들어도 작성자는 이 토큰의 주인이 되므로, 본인 토큰을 쓰는 한
// 지금 안전장치와 동일하다 — 남이 이 토큰을 얻지 않는 한 남용될 수 없다.
const LS_GH_TOKEN = 'bra_gh_token';
function ghToken() { return (localStorage.getItem(LS_GH_TOKEN) || '').trim(); }

function configureGhToken() {
  if (!isMaster()) { window.alert('먼저 마스터 모드를 켜 주세요.'); return; }
  const has = !!ghToken();
  const next = window.prompt(
    (has
      ? '저장된 토큰이 있습니다. 바꿀 토큰을 입력하거나, 비워 두고 확인을 누르면 지웁니다.\n\n'
      : 'GitHub 개인 토큰(Fine-grained PAT)을 입력하세요.\n' +
        'github.com → Settings → Developer settings → Fine-grained tokens 에서 만들되,\n' +
        `저장소를 ${REPO} 하나로 지정하고 'Issues: Read and write' 권한만 주면 됩니다.\n\n`) +
    '이 브라우저에만 저장되며, 다른 곳으로 전송되지 않습니다.',
    ''
  );
  if (next === null) return;   // 취소
  const v = next.trim();
  if (!v) {
    if (has) { localStorage.removeItem(LS_GH_TOKEN); window.alert('토큰을 지웠습니다. 다음부터는 다시 GitHub 로그인이 필요합니다.'); }
    renderMasterBtn();
    return;
  }
  localStorage.setItem(LS_GH_TOKEN, v);
  window.alert('토큰을 저장했습니다. 이제 이 브라우저에서는 URL 등록·텔레그램 전송이 로그인 없이 바로 처리됩니다.');
  renderMasterBtn();
}

async function ghApiCall(path, opts = {}) {
  const res = await fetch(`https://api.github.com${path}`, {
    ...opts,
    headers: {
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Authorization': `Bearer ${ghToken()}`,
      ...(opts.headers || {}),
    },
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try { const d = await res.json(); if (d.message) msg = d.message; } catch { /* 본문 없음 */ }
    const err = new Error(msg);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

const GH_POLL_MS = 4000;
const GH_POLL_TIMEOUT_MS = 5 * 60 * 1000;   // 5분 — Gemini 영상 직접 분석은 몇 분 걸릴 수 있다

/* 이슈를 만들고 닫힐 때까지 지켜본 뒤 마지막 댓글을 돌려준다.
   summarize-url·send-report·delete-report 세 워크플로가 전부 '댓글 남기고
   이슈 닫기'로 끝나는 같은 방식이라, 이 함수 하나로 셋 다 처리된다. */
async function ghRunAndWait(title, body, onStatus) {
  const issue = await ghApiCall(`/repos/${REPO}/issues`, {
    method: 'POST', body: JSON.stringify({ title, body }),
  });
  onStatus?.(`⏳ 처리를 요청했습니다 (이슈 #${issue.number}) — 끝날 때까지 기다립니다…`);
  const started = Date.now();
  while (Date.now() - started < GH_POLL_TIMEOUT_MS) {
    await new Promise((r) => setTimeout(r, GH_POLL_MS));
    const cur = await ghApiCall(`/repos/${REPO}/issues/${issue.number}`);
    if (cur.state === 'closed') {
      const comments = await ghApiCall(`/repos/${REPO}/issues/${issue.number}/comments`);
      return { issue: cur, message: comments.length ? comments[comments.length - 1].body : '' };
    }
  }
  return { issue, timeout: true };
}

/* 토큰이 있으면 API 로 바로 실행해 기다리고, 없으면 예전처럼 '새 이슈' 페이지를
   연다(사람이 로그인해서 직접 제출). 토큰이 있는데 실패하면(만료·권한 부족 등)
   원인을 알리고 마찬가지로 새 이슈 페이지를 열어 준다 — 아예 막히지는 않는다. */
async function runOrOpenIssue(title, body, onStatus) {
  const openManually = () => window.open(
    `https://github.com/${REPO}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`,
    '_blank', 'noopener');
  if (!ghToken()) { openManually(); return { opened: true }; }
  try {
    return await ghRunAndWait(title, body, onStatus);
  } catch (err) {
    const reason = err.status === 401 ? 'GitHub 토큰이 잘못됐거나 만료됐습니다.'
      : err.status === 403 ? 'GitHub 토큰에 이 저장소의 Issues 쓰기 권한이 없습니다.'
      : (err.message || '알 수 없는 오류');
    onStatus?.(`⚠️ ${reason} 새 이슈 페이지로 대신 엽니다.`);
    openManually();
    return { fallback: true, error: reason };
  }
}

// 텔레그램 전송 요청 — 카드의 📨 버튼.
// 봇 토큰은 저장소 시크릿에만 있으므로 브라우저가 직접 보낼 수는 없다.
// 삭제·요약과 같은 방식으로 GitHub 이슈를 열고, 워크플로가 리포트 전문(01~08)과
// 유튜브 링크를 텔레그램으로 보낸다. GitHub 토큰이 저장돼 있으면 로그인 없이
// API 로 바로 처리되고, 끝날 때까지 기다렸다가 결과를 알려 준다.
async function requestSend(r, btnEl) {
  const skipLogin = !!ghToken();
  if (!window.confirm(
      `이 리포트 전문을 텔레그램으로 보낼까요?\n\n${r.title}` +
      (skipLogin ? '' : '\n\n확인을 누르면 GitHub 요청 페이지가 열립니다.'))) return;
  const title = '[전송] ' + r.id;
  const body = '아래 리포트의 전문(01 핵심 개요 ~ 08 용어 사전)과 영상 링크를 ' +
    '텔레그램으로 보내 주세요.\n\n' +
    `- id: ${r.id}\n- 제목: ${r.title}\n- 영상: ${r.video || ''}\n`;

  if (!skipLogin) {
    window.open(`https://github.com/${REPO}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`,
                '_blank', 'noopener');
    return;
  }

  const originalText = btnEl ? btnEl.textContent : '';
  const originalTitle = btnEl ? btnEl.title : '';
  if (btnEl) { btnEl.disabled = true; btnEl.textContent = '⏳'; }
  const result = await runOrOpenIssue(title, body, (s) => { if (btnEl) btnEl.title = s; });
  if (btnEl) { btnEl.disabled = false; btnEl.textContent = originalText; btnEl.title = originalTitle; }

  if (result.timeout) {
    window.alert(`아직 처리 중입니다 — 이슈 #${result.issue.number} 에서 직접 확인해 주세요.\n` +
      `https://github.com/${REPO}/issues/${result.issue.number}`);
  } else if (result.message) {
    window.alert(result.message);
  }
  // result.fallback 이면 runOrOpenIssue 가 이미 안내하고 새 창을 열었다
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
// live/ 는 라이브 다시보기 링크(공유 버튼이 주는 형식, ?si=... 가 붙고 v= 파라미터가 없다)다.
// run_pipeline.py 의 _extract_video_id() 는 이미 지원하는데 여기 검증만 빠져 있어서,
// 서버까지 가지도 못하고 "올바른 유튜브 주소가 아닙니다"로 화면에서 막히고 있었다.
const YT_RE = /^(https?:\/\/)?(www\.)?(youtube\.com\/(watch\?v=|shorts\/|embed\/|live\/)|youtu\.be\/)[\w-]{6,}/i;

// GitHub 토큰이 저장돼 있으면 로그인 없이 API 로 바로 요약을 요청하고,
// 워크플로가 끝날 때까지 기다렸다가 결과를 이 자리에 보여 준다.
// 토큰이 없으면 예전처럼 '새 이슈' 페이지가 열려 직접 로그인해서 제출한다.
async function requestSummary() {
  const input = document.getElementById('yt-url');
  const hint = document.getElementById('yt-hint');
  const btn = document.getElementById('yt-submit');
  let url = (input.value || '').trim();
  if (!url) { input.focus(); return; }
  if (!/^https?:\/\//i.test(url)) url = 'https://' + url;
  if (!YT_RE.test(url)) {
    hint.innerHTML = '⚠️ 올바른 유튜브 주소가 아닙니다. 예) https://www.youtube.com/watch?v=...';
    hint.classList.add('err');
    return;
  }
  hint.classList.remove('err');
  const title = '[요약] ' + url;
  const body = '아래 유튜브 영상을 이차전지 리포트로 요약해 주세요.\n\n' + url + '\n';

  if (!ghToken()) {
    window.open(`https://github.com/${REPO}/issues/new?title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`,
                '_blank', 'noopener');
    hint.innerHTML = '↗️ GitHub 페이지에서 <b>‘Submit new issue’</b>를 눌러 주세요. ' +
      '제출 후 1~3분 뒤 이 목록에 리포트가 추가됩니다.';
    return;
  }

  if (btn) btn.disabled = true;
  hint.innerHTML = '⏳ 요청을 보내는 중…';
  const result = await runOrOpenIssue(title, body, (s) => { hint.innerHTML = s; });
  if (btn) btn.disabled = false;

  if (result.timeout) {
    hint.innerHTML = `⏳ 아직 처리 중입니다 — <a href="https://github.com/${REPO}/issues/${result.issue.number}" ` +
      `target="_blank" rel="noopener">이슈 #${result.issue.number}</a> 에서 확인해 주세요.`;
  } else if (result.message) {
    hint.innerHTML = result.message.replace(/\n/g, '<br>');
    input.value = '';
    reload();   // 새 리포트가 목록에 반영됐을 수 있으니 다시 불러온다
  }
  // result.fallback 이면 runOrOpenIssue 가 이미 안내하고 새 창을 열었다
}

function render() { renderStats(); renderPills(); renderChannels(); renderFavTools(); renderCards(); }

/* reports.json 을 다시 받아 화면을 갱신한다. init() 의 최초 로드와,
   URL 등록·전송이 API 로 끝난 뒤의 '방금 반영됐을 수 있으니 새로고침'에서
   함께 쓴다. 실패해도 기존 ALL 을 비우지 않는다 — 성공 뒤의 일시적 네트워크
   오류로 화면이 통째로 빈 목록이 되면 안 된다. */
async function reload() {
  try {
    const res = await fetch('../data/reports.json', { cache: 'no-cache' });
    const data = await res.json();
    // 최신순 정렬은 여기서 한 번만. 예전에는 검색어를 한 글자 칠 때마다
    // 367건을 다시 정렬했는데, 순서가 바뀔 일이 없으니 헛일이었다.
    ALL = (Array.isArray(data.reports) ? data.reports : [])
      .sort((a, b) => (a.date < b.date ? 1 : -1));
    CHANNEL_ROSTER = Array.isArray(data.channels) ? data.channels : [];
    pruneStaleIds();
    const stamp = document.getElementById('generated');
    if (stamp && data.generated_at) stamp.textContent = '최근 갱신: ' + data.generated_at.replace('T', ' ').slice(0, 16);
  } catch (e) {
    console.error('reports.json 로드 실패', e);
  }
  render();
}

async function init() {
  await reload();

  // 주소에 ?p=3 이 있으면 그 페이지부터 — 새로고침·뒤로가기·링크 공유에 쓰인다
  const wanted = parseInt(new URL(window.location.href).searchParams.get('p') || '1', 10);
  page = Number.isFinite(wanted) && wanted > 0 ? wanted : 1;

  const search = document.getElementById('search');
  search.addEventListener('input', () => { searchTerm = search.value.trim(); resetPage(); renderCards(); });

  // 마스터 모드 토글 · GitHub 토큰 설정(로그인 없이 바로 실행)
  const mb = document.getElementById('master-btn');
  if (mb) mb.addEventListener('click', toggleMaster);
  const tb = document.getElementById('gh-token-btn');
  if (tb) tb.addEventListener('click', configureGhToken);
  renderMasterBtn();

  // 홈 버튼: 목록 최상단(홈) 상태로 되돌리며 새로고침
  const homeBtn = document.getElementById('home-btn');
  if (homeBtn) {
    homeBtn.addEventListener('click', (e) => {
      e.preventDefault();
      // 홈은 '처음 상태' — 페이지 번호도 떼고 최신 데이터로 새로 받는다
      const url = new URL(window.location.href);
      url.searchParams.delete('p');
      window.location.replace(url);
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
}
document.addEventListener('DOMContentLoaded', init);
