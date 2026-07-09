// 마지막으로 연 프로젝트 ID를 localStorage에 기억한다. 브라우저를 껐다 켜도 같은
// 워크스페이스로 복귀하기 위한 최소 상태(서버에 별도 "last opened" 필드를 두지 않는다).
// SSR/빌드 중엔 window가 없으므로 모든 접근을 가드한다.
const KEY = "pondas:last_project";

export function getLastProject(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(KEY);
  } catch {
    return null; // 프라이빗 모드 등에서 접근 차단될 수 있음 — 조용히 무시.
  }
}

export function setLastProject(id: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, id);
  } catch {
    /* ignore */
  }
}

export function clearLastProject(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

/**
 * 프로젝트 목록에서 "갈 곳"을 고른다: 기억된 마지막 프로젝트가 목록에 아직 있으면 그것,
 * 아니면 목록의 첫 번째(최신). 목록이 비면 null.
 */
export function pickProject<T extends { id: string }>(projects: T[]): string | null {
  if (!projects.length) return null;
  const last = getLastProject();
  if (last && projects.some((p) => p.id === last)) return last;
  return projects[0].id;
}
