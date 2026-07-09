// 백엔드 API 클라이언트 — Clerk JWT를 Authorization으로 싣는다(D24).
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const BASE = API_BASE;

// E2E 모드(dev 전용) — Clerk 사인인 우회. 백엔드도 E2E_AUTH_BYPASS로 매칭.
// E2E 우회는 개발 빌드에서만 — prod 빌드(NODE_ENV=production)에선 강제로 off(NEXT_PUBLIC_E2E가
// 실수로 켜져도 프로덕션 UI에서 로그아웃 숨김/토큰 우회가 새지 않도록 fail-safe).
export const E2E = process.env.NEXT_PUBLIC_E2E === "1" && process.env.NODE_ENV !== "production";

/**
 * apiFetch — 백엔드 호출 공통 창구. 프론트의 모든 API 요청이 이 함수 하나를 거친다.
 *
 * 무슨 일을 하나: 주소(path)와 옵션을 받아 백엔드에 fetch 요청을 보낸다. 로그인 토큰을
 *   Authorization 헤더에 자동으로 실어주고, 응답이 실패면 상황에 맞는 에러로 바꿔 던진다.
 *   - 4xx(클라이언트 잘못): 백엔드가 준 사용자용 메시지(예: "desks are full")를 그대로 노출.
 *   - 5xx(서버 잘못): 내부 정보 누출 방지 위해 일반 메시지만 보이고 상세는 콘솔/서버 로그에만.
 * 누가 부르나: 프론트 거의 전부 — 페이지·패널·오버레이의 데이터 로드/저장.
 * 연결: 받는 쪽 → 백엔드의 각 라우터(backend/app/routers/*). 토큰 검증 → backend/app/auth.py.
 */
export async function apiFetch<T>(
  path: string,
  opts: RequestInit & { token?: string | null } = {},
): Promise<T> {
  const { token, headers, ...rest } = opts;
  const res = await fetch(`${BASE}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  });
  if (!res.ok) {
    // 4xx(클라이언트/검증)는 백엔드 detail이 유저용 메시지(예: "desks are full") → 노출.
    // 5xx(서버)는 내부 정보 누출 방지 → 일반 메시지(상세는 콘솔/서버 로그에만).
    if (res.status >= 500) {
      console.error("server error", res.status, await res.text().catch(() => ""));
      throw new Error("Something went wrong. Please try again.");
    }
    let detail = "";
    try {
      const j = await res.json();
      detail = typeof j?.detail === "string" ? j.detail : "";
    } catch { /* non-JSON */ }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// P0 팀 템플릿(GET /templates와 일치, D44 — Data 제외). 정적 폴백.
export const TEAM_TEMPLATES = [
  { key: "planning", name: "Product Planning", description: "Defines what to build and why — PRDs and specs.", starter: "PM" },
  { key: "research", name: "Research", description: "Investigates markets, competitors, user needs.", starter: "Researcher" },
  { key: "design", name: "Design", description: "Designs and builds the UI — code + screenshots.", starter: "Product Designer" },
  { key: "development", name: "Development", description: "Implements, verifies, and reviews working software.", starter: "Software Engineer" },
] as const;
