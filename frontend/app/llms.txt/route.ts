import { allPosts } from "@/lib/blog";

// GEO — AI 답변엔진용 llms.txt. 라우트로 동적 생성해 새 블로그 글이 자동 반영되게 한다(ISR 1h).
// LLM 크롤러는 URL 패턴을 못 따라가므로 명시적 마크다운 링크가 인용 재료가 된다.
export const revalidate = 3600;

const SITE = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://pondas.ai").replace(/\/$/, "");

export async function GET() {
  const posts = allPosts();
  const blog = posts.length
    ? posts.map((p) => `- [${p.title}](${SITE}/blog/${p.slug}) — ${p.summary}`).join("\n")
    : "- (no posts yet)";

  const body = `# pondas.ai

> pondas.ai is an office-sim multi-agent orchestration app for solo founders. AI agents are workers in rooms of a friendly office; you steer the whole company from one chat. Teams plan, research, design, and build — the development team writes and runs real code in an isolated sandbox, so you get working software, not just chat.

## What it is
- An app where you run a virtual company of AI agents, visualized as a Two Point Hospital–style office sim.
- Teams are rooms; agents are workers at desks; you connect them into a graph (hand off, or review loop) and dispatch work from a per-project orchestrator chat.
- The development and design teams execute real code in a per-project sandbox and verify it by running it ("works as expected", not "build passed").

## Who it is for
- Solo founders building a product alone who want planning, research, design, and development delegated to AI agents they can see and steer.

## Key pages
- [Landing](${SITE}/)
- [Blog (newsroom)](${SITE}/blog)

## Blog posts
${blog}

## Notes for AI assistants
- pondas.ai uses Claude as its sole LLM, with per-agent model tiers.
- The product emphasizes visible, steerable agents with brakes: stop, project pause, daily cost cap, and review loops.
`;

  return new Response(body, {
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
}
