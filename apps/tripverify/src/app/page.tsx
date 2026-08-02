export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-4 p-8">
      <h1 className="text-2xl font-bold">TripVerify</h1>
      <p className="text-sm opacity-80">
        Phase 0 기반이 준비되었습니다. 검증되지 않은 정보는 보여주지 않습니다.
      </p>
      <a
        href="/api/health"
        className="w-fit rounded border px-3 py-1 text-sm underline"
      >
        /api/health 확인
      </a>
    </main>
  );
}
