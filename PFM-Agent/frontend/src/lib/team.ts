/**
 * 팀 협업 API 클라이언트.
 *
 * ⚠️ 폐쇄망 연결
 * 한 PC 가 호스트로 백엔드를 열고, 다른 PC 들이 그 주소로 접속한다.
 * 참여자 PC 는 `VITE_TEAM_SERVER_URL` 에 호스트 주소를 넣으면 되고,
 * 값이 없으면 이 PC 의 백엔드를 사용한다.
 */

import { API_BASE } from "./api";

/** 팀 서버 주소 (없으면 이 PC 의 백엔드) */
export const TEAM_BASE: string =
  import.meta.env.VITE_TEAM_SERVER_URL ?? API_BASE;

/** 내 정보 */
export interface TeamMe {
  member_id: string;
  display_name: string;
  enabled: boolean;
  reason: string;
}

/** 대화방 / 회의방 */
export interface TeamRoom {
  id: string;
  name: string;
  kind: "chat" | "meeting";
  created_by: string;
  created_at: string;
  closed_at: string | null;
  is_open: boolean;
  member_ids: string[];
  message_count: number;
  last_message_at: string | null;
}

/** 주고받은 파일 */
export interface TeamAttachment {
  id: string;
  filename: string;
  media_type: "image" | "video" | "file";
  size_bytes: number;
  sha256: string;
}

/** 대화 메시지 */
export interface TeamMessage {
  id: number;
  room_id: string;
  member_id: string;
  kind: "text" | "file" | "image" | "video" | "system";
  body: string;
  created_at: string;
  is_deleted: boolean;
  attachment: TeamAttachment | null;
}

/** WebSocket 으로 오는 이벤트 */
export interface TeamEvent {
  type: "connected" | "message" | "message_deleted" | "room_closed" | "ping" | "error";
  message?: TeamMessage;
  room?: TeamRoom;
}

/**
 * 응답을 확인하고 JSON 을 돌려준다.
 *
 * 실패 시 백엔드가 보낸 **한글 안내**를 그대로 오류 메시지로 쓴다.
 */
async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `요청이 실패했습니다 (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      // 본문이 JSON 이 아니면 기본 메시지를 쓴다.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

/** 내 정보 조회 */
export async function fetchMe(): Promise<TeamMe> {
  return parse<TeamMe>(await fetch(`${TEAM_BASE}/api/team/me`));
}

/** 방 목록 조회 */
export async function fetchRooms(): Promise<TeamRoom[]> {
  const data = await parse<{ rooms: TeamRoom[] }>(
    await fetch(`${TEAM_BASE}/api/team/rooms`),
  );
  return data.rooms;
}

/** 대화방 또는 회의방 만들기 */
export async function createRoom(
  name: string,
  kind: "chat" | "meeting",
): Promise<TeamRoom> {
  return parse<TeamRoom>(
    await fetch(`${TEAM_BASE}/api/team/rooms`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, kind }),
    }),
  );
}

/** 회의 종료 */
export async function closeRoom(roomId: string): Promise<TeamRoom> {
  return parse<TeamRoom>(
    await fetch(`${TEAM_BASE}/api/team/rooms/${roomId}/close`, { method: "POST" }),
  );
}

/**
 * 메시지 목록 조회.
 *
 * @param afterId 이 번호보다 큰 메시지만 (실시간 갱신용)
 */
export async function fetchMessages(
  roomId: string,
  afterId = 0,
): Promise<TeamMessage[]> {
  const data = await parse<{ messages: TeamMessage[] }>(
    await fetch(
      `${TEAM_BASE}/api/team/rooms/${roomId}/messages?after_id=${afterId}`,
    ),
  );
  return data.messages;
}

/** 글 보내기 */
export async function sendMessage(
  roomId: string,
  body: string,
): Promise<TeamMessage> {
  return parse<TeamMessage>(
    await fetch(`${TEAM_BASE}/api/team/rooms/${roomId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body }),
    }),
  );
}

/** 파일 · 이미지 · 영상 보내기 */
export async function uploadFile(
  roomId: string,
  file: File,
  body = "",
): Promise<TeamMessage> {
  const form = new FormData();
  form.append("file", file);
  form.append("body", body);
  return parse<TeamMessage>(
    await fetch(`${TEAM_BASE}/api/team/rooms/${roomId}/upload`, {
      method: "POST",
      body: form,
    }),
  );
}

/** 메시지 삭제 (기록은 남는다) */
export async function deleteMessage(messageId: number): Promise<TeamMessage> {
  return parse<TeamMessage>(
    await fetch(`${TEAM_BASE}/api/team/messages/${messageId}`, {
      method: "DELETE",
    }),
  );
}

/** 첨부 파일 주소 (이미지/영상 표시 및 내려받기용) */
export function attachmentUrl(attachmentId: string): string {
  return `${TEAM_BASE}/api/team/attachments/${attachmentId}/download`;
}

/** 회의록 주소 */
export function transcriptUrl(roomId: string): string {
  return `${TEAM_BASE}/api/team/rooms/${roomId}/transcript`;
}

/**
 * 방의 실시간 이벤트를 구독한다.
 *
 * 연결에 실패해도 화면이 멈추지 않도록 null 을 돌려준다.
 * (호출부가 주기적 재조회로 대체한다)
 */
export function openTeamSocket(
  roomId: string,
  onEvent: (event: TeamEvent) => void,
): WebSocket | null {
  try {
    const url = `${TEAM_BASE.replace(/^http/, "ws")}/ws/team/${roomId}`;
    const socket = new WebSocket(url);
    socket.onmessage = (raw) => {
      try {
        const event = JSON.parse(raw.data as string) as TeamEvent;
        if (event.type !== "ping") onEvent(event);
      } catch {
        // 형식이 이상한 메시지는 무시한다.
      }
    };
    return socket;
  } catch {
    return null;
  }
}
