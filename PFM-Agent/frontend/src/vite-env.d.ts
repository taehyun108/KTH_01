/// <reference types="vite/client" />

/**
 * Vite 환경변수 타입 정의.
 *
 * ⚠️ 포터블 원칙: 백엔드 주소는 하드코딩하지 않고 환경변수로 받는다.
 *    설정하지 않으면 로컬 기본값(http://127.0.0.1:8756)을 사용한다.
 */
interface ImportMetaEnv {
  readonly VITE_BACKEND_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
