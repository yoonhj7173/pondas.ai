"use client";

// 결과 인-플로우 렌더러(Phase 2, D51) — sanitized 마크다운(raw HTML 미렌더 = stored-XSS 차단).
// office 기본 청크를 가볍게 유지하려고 소비처에서 next/dynamic으로 lazy 로드한다.
// 블로그(app/blog)의 ReactMarkdown+remarkGfm 패턴 재사용 — rehype-raw 없음(안전).
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={className ?? "prose-result"}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
