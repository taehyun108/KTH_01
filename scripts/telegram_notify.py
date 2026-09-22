"""텔레그램 알림 — 새로 발행된 리포트를 봇으로 보낸다.

run_pipeline 이 남긴 .pipeline_state.json 의 new_ids 를 읽어, 그중 이차전지와
연결되는 것만 보낸다. <커밋이 끝난 뒤>에 도는 것이 중요하다 — 사이트에 실제로
올라간 리포트만 알려야 링크가 죽지 않는다.

토큰(TELEGRAM_BOT_TOKEN)이나 대화방 id(TELEGRAM_CHAT_ID)가 없으면 아무 일도 하지
않고 조용히 지나간다. 알림은 부가 기능이므로, 여기서 실패해도 파이프라인 자체는
성공이어야 한다 — 리포트는 이미 만들어져 사이트에 올라가 있다.

    python scripts/telegram_notify.py           # 이번 실행의 신규 리포트 발송
    python scripts/telegram_notify.py --test    # 토큰·대화방 연결 확인
"""
from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import quote

import requests

from config import ROOT, SITE_BASE_URL

API = "https://api.telegram.org/bot{token}/{method}"

# 어떤 연관도까지 보낼지. generate_report 가 붙이는 relation 값을 그대로 쓴다.
#   direct   🔋 배터리를 직접 다룬 글
#   indirect 🔋 금리·관세처럼 배터리 산업에 이어지는 글
#   context  🏭 배터리 언급은 없고 산업 환경으로서만 의미가 있는 글
# 기본값은 direct+indirect — 이차전지와 실제로 연결되는 글만 보낸다.
RELATIONS = [r.strip() for r in
             os.getenv("TELEGRAM_RELATIONS", "direct,indirect").split(",") if r.strip()]

# 한 실행에서 보낼 최대 건수. 백필처럼 수십 건이 한꺼번에 나온 날 대화방이
# 도배되는 것을 막는다.
MAX_PER_RUN = int(os.getenv("TELEGRAM_MAX_PER_RUN", "10"))

CATEGORY_LABELS = {
    "macro": "📈 거시경제",
    "global-policy": "🌍 글로벌 정책·시사",
    "global-market": "📊 글로벌 산업·시황",
    "korea-policy": "🇰🇷 국내 정책·시사",
    "korea-market": "🇰🇷 국내 산업·시황",
}
RELATION_LABELS = {"direct": "🔋 직접", "indirect": "🔋 간접", "context": "🏭 산업"}


def _escape(text: str) -> str:
    """텔레그램 HTML 파싱 모드에서 쓰는 세 글자만 막는다."""
    return (str(text or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def missing() -> list[str]:
    """등록되지 않은 시크릿 이름. 어느 쪽이 빠졌는지 <정확히> 말하기 위한 것이다.

    둘 다 없다고 뭉뚱그리면, 토큰은 멀쩡히 넣어 둔 사람이 토큰을 의심하며 시간을
    버린다(2026-09-22 에 실제로 그랬다).
    """
    return [k for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.getenv(k)]


def enabled() -> bool:
    return not missing()


def _call(method: str, payload: dict) -> dict:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    resp = requests.post(API.format(token=token, method=method),
                         json=payload, timeout=20)
    body = resp.json()
    if not body.get("ok"):
        # description 에 토큰은 실리지 않는다(요청 URL 에만 있다).
        raise RuntimeError(f"{method} 실패 — {body.get('description', resp.status_code)}")
    return body["result"]


# 텔레그램 한 메시지의 상한. 넘기면 전송 자체가 거부된다.
MAX_CHARS = 4096


def split_message(parts: list[str], limit: int = MAX_CHARS) -> list[str]:
    """문단 목록을 상한 이하의 메시지 여러 개로 묶는다.

    문단 사이에서 끊는 것을 우선한다 — 태그 한가운데서 자르면 HTML 파싱이
    깨져 전송이 통째로 거부된다. 문단 하나가 혼자 상한을 넘으면 그때만
    문장 단위로 쪼갠다.
    """
    out: list[str] = []
    buf = ""
    for part in parts:
        while len(part) > limit:
            head = part[:limit]
            cut = max(head.rfind("\n"), head.rfind(". "), head.rfind("다. "))
            cut = cut + 1 if cut > limit // 2 else limit
            if buf:
                out.append(buf)
                buf = ""
            out.append(part[:cut].strip())
            part = part[cut:].lstrip()
        if not part:
            continue
        candidate = f"{buf}\n\n{part}" if buf else part
        if len(candidate) > limit:
            out.append(buf)
            buf = part
        else:
            buf = candidate
    if buf:
        out.append(buf)
    return out


def send_text(parts: list[str]) -> int:
    """긴 글을 상한에 맞춰 나눠 보낸다. 보낸 메시지 수를 돌려준다."""
    chunks = split_message(parts)
    for i, chunk in enumerate(chunks):
        _call("sendMessage", {
            "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
            "text": chunk,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        })
        if i < len(chunks) - 1:
            time.sleep(1.2)
    return len(chunks)


def format_report(report: dict) -> str:
    cat = CATEGORY_LABELS.get(report.get("category", ""), "")
    rel = RELATION_LABELS.get(report.get("relation", ""), "")
    tags = " · ".join(t for t in (cat, rel) if t)
    lines = [
        f"<b>{_escape(report.get('title'))}</b>",
        "",
        _escape(report.get("summary")),
        "",
        f"{tags}",
        f"📺 {_escape(report.get('channel'))} · {_escape(report.get('date'))}",
        # 리포트 파일명은 한글이라 그대로 넣으면 링크가 깨지는 클라이언트가 있다.
        f'<a href="{SITE_BASE_URL}/news/{quote(report.get("url", ""))}">리포트 읽기</a>'
        f' · <a href="{_escape(report.get("video", ""))}">영상 보기</a>',
    ]
    return "\n".join(lines)


def send_reports(reports: list[dict]) -> int:
    """이차전지와 연결되는 리포트만 골라 보낸다. 보낸 건수를 돌려준다.

    reports 는 <보낼 순서대로>(오래된 것부터) 넘긴다. 상한을 넘으면 뒤쪽,
    즉 최신 것을 남긴다.
    """
    if not enabled():
        print(f"  텔레그램: {' · '.join(missing())} 미등록 — 알림을 건너뜁니다")
        return 0

    targets = [r for r in reports if r.get("relation") in RELATIONS]
    skipped = len(reports) - len(targets)
    if len(targets) > MAX_PER_RUN:
        print(f"  텔레그램: {len(targets)}건 중 최신 {MAX_PER_RUN}건만 보냅니다")
        targets = targets[-MAX_PER_RUN:]

    sent = 0
    for r in targets:
        try:
            _call("sendMessage", {
                "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
                "text": format_report(r),
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            })
            sent += 1
        except Exception as exc:  # noqa: BLE001
            # 한 건이 실패해도 나머지는 보낸다. 알림 실패로 실행을 접지 않는다.
            print(f"  텔레그램 전송 실패 {r.get('id', '?')}: {exc}", file=sys.stderr)
        # 텔레그램은 같은 대화방에 초당 1건 정도까지만 받아 준다.
        time.sleep(1.2)

    print(f"  텔레그램: {sent}건 전송"
          + (f" · 연관도 밖 {skipped}건 제외({'/'.join(RELATIONS)}만 발송)" if skipped else ""))
    return sent


def _print_candidates(username: str) -> None:
    """봇이 최근에 받은 대화에서 등록할 chat id 후보를 찍는다.

    브라우저 주소창에 토큰을 붙여 넣어 getUpdates 를 여는 대신(주소창 기록에
    토큰이 남는다) 여기서 대신 물어본다.
    """
    seen: dict[str, str] = {}
    for u in _call("getUpdates", {}):
        for key in ("message", "channel_post", "my_chat_member"):
            chat = (u.get(key) or {}).get("chat") or {}
            if chat.get("id") is not None:
                name = chat.get("title") or chat.get("username") or \
                    chat.get("first_name") or ""
                seen[str(chat["id"])] = f"{chat.get('type', '')} {name}".strip()
    if seen:
        print("\n등록할 chat id 후보 — 이 값을 TELEGRAM_CHAT_ID 에 그대로 넣으세요:",
              file=sys.stderr)
        for cid, label in seen.items():
            print(f"  TELEGRAM_CHAT_ID = {cid}   ({label})", file=sys.stderr)
    else:
        print(f"\n봇이 받은 최근 대화가 없습니다. 텔레그램에서 @{username} 에게 "
              "아무 메시지나 보낸 뒤(그룹이면 봇을 초대한 뒤) 다시 실행하세요.",
              file=sys.stderr)


def _test() -> int:
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        print("TELEGRAM_BOT_TOKEN 이 없습니다 — 시크릿을 먼저 등록하세요.", file=sys.stderr)
        return 1

    me = _call("getMe", {})
    username = me.get("username", "")
    print(f"봇 확인됨 — @{username} ({me.get('first_name')})")

    if not os.getenv("TELEGRAM_CHAT_ID"):
        print("TELEGRAM_CHAT_ID 가 비어 있습니다.", file=sys.stderr)
        _print_candidates(username)
        return 1

    try:
        _call("sendMessage", {
            "chat_id": os.getenv("TELEGRAM_CHAT_ID"),
            "text": "🔋 이차전지 리포트 아카이브 — 알림 연결이 정상입니다.",
        })
    except RuntimeError as exc:
        # 값이 <있지만 틀린> 경우가 가장 답답하다. 예전에는 여기서 그냥 죽어서,
        # 정작 후보를 보여 줘야 할 자리에 오류만 남았다(2026-09-22).
        print(f"\n전송 실패 — {exc}", file=sys.stderr)
        print("등록된 TELEGRAM_CHAT_ID 로는 보낼 수 없습니다. 흔한 원인:\n"
              "  · chat.id 가 아닌 다른 숫자(update_id·message_id·봇 id)를 넣음\n"
              "  · 그룹·채널인데 앞의 '-100' 을 빼고 넣음\n"
              "  · 값 앞뒤에 따옴표나 공백이 섞임", file=sys.stderr)
        _print_candidates(username)
        return 1

    print("테스트 메시지를 보냈습니다. 텔레그램 대화방을 확인하세요.")
    return 0


def _from_state() -> int:
    """run_pipeline 이 이번 실행에서 새로 만든 리포트를 골라 보낸다."""
    if not enabled():
        print(f"  텔레그램: {' · '.join(missing())} 미등록 — 알림을 건너뜁니다")
        return 0
    try:
        state = json.loads((ROOT / ".pipeline_state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("  텔레그램: 이번 실행 기록이 없어 보낼 것이 없습니다")
        return 0

    new_ids = set(state.get("new_ids") or [])
    if not new_ids:
        print("  텔레그램: 신규 리포트 0건")
        return 0

    from build_index import load_existing
    # reports.json 은 최신순이다. 여기서 순서를 뒤집어 <오래된 것부터> 보내야
    # 대화방에서 시간 순서대로 읽힌다.
    fresh = [r for r in load_existing() if r.get("id") in new_ids]
    send_reports(list(reversed(fresh)))
    return 0


if __name__ == "__main__":
    if "--test" in sys.argv:
        raise SystemExit(_test())
    raise SystemExit(_from_state())
