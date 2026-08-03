/**
 * 팀 협업 패널 — 같은 그룹 구성원끼리 대화·회의·파일 공유.
 *
 * 구성
 *   왼쪽 : 대화방/회의방 목록 + 새로 만들기
 *   오른쪽: 대화 내용 + 입력창 + 파일 보내기
 *
 * 새 메시지는 WebSocket 으로 즉시 받아 화면에 붙인다.
 * 연결이 끊기면 주기적으로 다시 불러와(polling) 대화가 멈추지 않게 한다.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  closeRoom,
  createRoom,
  deleteMessage,
  fetchMe,
  fetchMessages,
  fetchRooms,
  openTeamSocket,
  sendMessage,
  transcriptUrl,
  uploadFile,
  attachmentUrl,
  type TeamMe,
  type TeamMessage,
  type TeamRoom,
} from "../lib/team";

/** 연결이 끊겼을 때 다시 불러오는 주기(ms) */
const POLL_INTERVAL = 4000;

/** 시간을 HH:MM 으로 표시한다. */
function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 파일 크기를 사람이 읽는 단위로 바꾼다. */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

export function TeamPanel() {
  const [me, setMe] = useState<TeamMe | null>(null);
  const [rooms, setRooms] = useState<TeamRoom[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [messages, setMessages] = useState<TeamMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const activeRoom = useMemo(
    () => rooms.find((room) => room.id === activeId) ?? null,
    [rooms, activeId],
  );

  // ------------------------------------------------------------
  // 초기 로딩
  // ------------------------------------------------------------
  const reloadRooms = useCallback(async () => {
    try {
      const list = await fetchRooms();
      setRooms(list);
      // 처음 열었을 때 첫 방을 자동 선택한다.
      setActiveId((current) => current || list[0]?.id || "");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "대화방을 불러오지 못했습니다.");
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        setMe(await fetchMe());
      } catch {
        setNotice("팀 기능을 사용할 수 없습니다. 백엔드가 실행 중인지 확인하세요.");
      }
      await reloadRooms();
    })();
  }, [reloadRooms]);

  // ------------------------------------------------------------
  // 방을 바꾸면 대화를 새로 불러온다
  // ------------------------------------------------------------
  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    void (async () => {
      try {
        setMessages(await fetchMessages(activeId));
      } catch (error) {
        setNotice(
          error instanceof Error ? error.message : "대화를 불러오지 못했습니다.",
        );
      }
    })();
  }, [activeId]);

  // ------------------------------------------------------------
  // 실시간 수신 (WebSocket) + 끊겼을 때 대비 폴링
  // ------------------------------------------------------------
  useEffect(() => {
    if (!activeId) return;

    const socket = openTeamSocket(activeId, (event) => {
      if (event.type === "message" && event.message) {
        const incoming = event.message;
        setMessages((prev) =>
          // 내가 보낸 메시지가 응답으로 먼저 들어온 경우 중복을 막는다.
          prev.some((item) => item.id === incoming.id) ? prev : [...prev, incoming],
        );
      } else if (event.type === "message_deleted" && event.message) {
        const removed = event.message;
        setMessages((prev) =>
          prev.map((item) => (item.id === removed.id ? removed : item)),
        );
      } else if (event.type === "room_closed") {
        void reloadRooms();
      }
    });

    // WebSocket 이 막혀 있어도 대화가 멈추지 않도록 주기적으로 확인한다.
    const timer = window.setInterval(() => {
      if (socket && socket.readyState === WebSocket.OPEN) return;
      void (async () => {
        const last = messages[messages.length - 1]?.id ?? 0;
        try {
          const fresh = await fetchMessages(activeId, last);
          if (fresh.length > 0) setMessages((prev) => [...prev, ...fresh]);
        } catch {
          // 조용히 무시한다. (다음 주기에 다시 시도)
        }
      })();
    }, POLL_INTERVAL);

    return () => {
      socket?.close();
      window.clearInterval(timer);
    };
    // messages 를 의존성에 넣으면 매 메시지마다 재연결되므로 제외한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, reloadRooms]);

  // 새 메시지가 오면 맨 아래로 스크롤한다.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ------------------------------------------------------------
  // 동작
  // ------------------------------------------------------------
  const handleCreateRoom = useCallback(
    async (kind: "chat" | "meeting") => {
      const label = kind === "meeting" ? "회의" : "대화방";
      const name = window.prompt(`새 ${label} 이름을 입력하세요`);
      if (!name?.trim()) return;
      try {
        const room = await createRoom(name.trim(), kind);
        await reloadRooms();
        setActiveId(room.id);
        setNotice("");
      } catch (error) {
        setNotice(error instanceof Error ? error.message : `${label}을 만들지 못했습니다.`);
      }
    },
    [reloadRooms],
  );

  const handleSend = useCallback(async () => {
    const body = draft.trim();
    if (!body || !activeId) return;
    setBusy(true);
    try {
      await sendMessage(activeId, body);
      setDraft("");
      setNotice("");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "메시지를 보내지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }, [draft, activeId]);

  const handleUpload = useCallback(
    async (file: File) => {
      if (!activeId) return;
      setBusy(true);
      setNotice(`'${file.name}' 을(를) 보내는 중입니다...`);
      try {
        await uploadFile(activeId, file);
        setNotice("");
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "파일을 보내지 못했습니다.");
      } finally {
        setBusy(false);
        if (fileRef.current) fileRef.current.value = "";
      }
    },
    [activeId],
  );

  const handleClose = useCallback(async () => {
    if (!activeRoom) return;
    if (!window.confirm(`'${activeRoom.name}' 회의를 종료할까요? (기록은 남습니다)`))
      return;
    try {
      await closeRoom(activeRoom.id);
      await reloadRooms();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "회의를 종료하지 못했습니다.");
    }
  }, [activeRoom, reloadRooms]);

  const handleDelete = useCallback(async (messageId: number) => {
    if (!window.confirm("이 메시지를 삭제할까요? (기록에는 남습니다)")) return;
    try {
      await deleteMessage(messageId);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "삭제하지 못했습니다.");
    }
  }, []);

  // ------------------------------------------------------------
  // 화면
  // ------------------------------------------------------------
  return (
    <div className="team">
      {/* --- 방 목록 --- */}
      <aside className="team-rooms">
        <div className="team-rooms-head">
          <strong>대화 / 회의</strong>
          <div className="team-room-buttons">
            <button type="button" onClick={() => void handleCreateRoom("chat")}>
              + 대화
            </button>
            <button type="button" onClick={() => void handleCreateRoom("meeting")}>
              + 회의
            </button>
          </div>
        </div>

        <ul className="team-room-list">
          {rooms.map((room) => (
            <li key={room.id}>
              <button
                type="button"
                className={room.id === activeId ? "active" : ""}
                onClick={() => setActiveId(room.id)}
              >
                <span className="team-room-name">
                  {room.kind === "meeting" ? "📋" : "💬"} {room.name}
                </span>
                <span className="team-room-meta">
                  {room.message_count}건{room.is_open ? "" : " · 종료됨"}
                </span>
              </button>
            </li>
          ))}
          {rooms.length === 0 && (
            <li className="team-empty">
              아직 대화방이 없습니다. 위의 버튼으로 만들어 보세요.
            </li>
          )}
        </ul>

        {me && (
          <div className="team-me">
            나: <b>{me.display_name}</b>
          </div>
        )}
      </aside>

      {/* --- 대화 --- */}
      <section className="team-chat">
        {activeRoom ? (
          <>
            <header className="team-chat-head">
              <div>
                <strong>{activeRoom.name}</strong>
                <span className="team-room-meta">
                  {activeRoom.kind === "meeting" ? " 회의" : " 대화"}
                  {activeRoom.is_open ? "" : " · 종료됨"}
                </span>
              </div>
              <div className="team-chat-actions">
                <a
                  href={transcriptUrl(activeRoom.id)}
                  target="_blank"
                  rel="noreferrer"
                >
                  기록 보기
                </a>
                {activeRoom.kind === "meeting" && activeRoom.is_open && (
                  <button type="button" onClick={() => void handleClose()}>
                    회의 종료
                  </button>
                )}
              </div>
            </header>

            <div className="team-messages">
              {messages.map((message) => {
                const mine = message.member_id === me?.member_id;
                if (message.kind === "system") {
                  return (
                    <div key={message.id} className="team-system">
                      {message.body}
                    </div>
                  );
                }
                return (
                  <div
                    key={message.id}
                    className={`team-message ${mine ? "mine" : ""}`}
                  >
                    <div className="team-message-head">
                      <b>{message.member_id}</b>
                      <span>{formatTime(message.created_at)}</span>
                      {mine && !message.is_deleted && (
                        <button
                          type="button"
                          className="team-delete"
                          onClick={() => void handleDelete(message.id)}
                        >
                          삭제
                        </button>
                      )}
                    </div>

                    {message.is_deleted ? (
                      <div className="team-deleted">삭제된 메시지입니다</div>
                    ) : (
                      <>
                        {message.attachment && (
                          <div className="team-attachment">
                            {message.attachment.media_type === "image" && (
                              <img
                                src={attachmentUrl(message.attachment.id)}
                                alt={message.attachment.filename}
                              />
                            )}
                            {message.attachment.media_type === "video" && (
                              <video
                                src={attachmentUrl(message.attachment.id)}
                                controls
                              />
                            )}
                            <a
                              href={attachmentUrl(message.attachment.id)}
                              download={message.attachment.filename}
                            >
                              📎 {message.attachment.filename} (
                              {formatSize(message.attachment.size_bytes)})
                            </a>
                          </div>
                        )}
                        {message.body && (
                          <div className="team-body">{message.body}</div>
                        )}
                      </>
                    )}
                  </div>
                );
              })}
              <div ref={bottomRef} />
            </div>

            {activeRoom.is_open ? (
              <div className="team-input">
                <input
                  ref={fileRef}
                  type="file"
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void handleUpload(file);
                  }}
                />
                <button
                  type="button"
                  title="파일 · 이미지 · 영상 보내기"
                  onClick={() => fileRef.current?.click()}
                  disabled={busy}
                >
                  📎
                </button>
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    // Enter 로 보내고, Shift+Enter 는 줄바꿈
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void handleSend();
                    }
                  }}
                  placeholder="메시지를 입력하세요 (Enter 전송 / Shift+Enter 줄바꿈)"
                  rows={2}
                />
                <button type="button" onClick={() => void handleSend()} disabled={busy}>
                  보내기
                </button>
              </div>
            ) : (
              <div className="team-closed">
                종료된 회의입니다. 기록은 계속 확인할 수 있습니다.
              </div>
            )}
          </>
        ) : (
          <div className="team-empty-chat">
            왼쪽에서 대화방을 선택하거나 새로 만들어 주세요.
          </div>
        )}

        {notice && <div className="team-notice">{notice}</div>}
      </section>
    </div>
  );
}
