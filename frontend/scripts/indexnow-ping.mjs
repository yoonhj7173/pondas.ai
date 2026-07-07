// IndexNow 핑 — Bing/Naver/Yandex 등에 URL 변경을 push(구글은 IndexNow 미지원, 별도).
// 의존성 0(Node 18+ 내장 fetch). 실행:
//   node scripts/indexnow-ping.mjs                 → sitemap 전체 URL 제출
//   node scripts/indexnow-ping.mjs https://pondas.ai/blog/새-글  → 지정 URL만
// 블로그 발행 파이프라인에서 새 글 URL을 인자로 넘겨 호출하면 됨.
//
// ⚠️ 신규 키는 검증 지연으로 첫 핑이 403(SiteVerificationNotCompleted)일 수 있음 — 정상, 나중에 재시도.

const SITE = (process.env.NEXT_PUBLIC_SITE_URL ?? "https://pondas.ai").replace(/\/$/, "");
const KEY = "b32c41acfa97f9f77d41045346aa1cfb"; // public/<KEY>.txt 와 동일해야 함
const HOST = new URL(SITE).host;

async function urlsFromSitemap() {
  const res = await fetch(`${SITE}/sitemap.xml`);
  if (!res.ok) throw new Error(`sitemap fetch ${res.status}`);
  const xml = await res.text();
  return [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
}

async function main() {
  const args = process.argv.slice(2).filter(Boolean);
  const urlList = args.length ? args : await urlsFromSitemap();
  if (!urlList.length) {
    console.error("no URLs to submit");
    process.exit(1);
  }

  const res = await fetch("https://api.indexnow.org/indexnow", {
    method: "POST",
    headers: { "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({
      host: HOST,
      key: KEY,
      keyLocation: `${SITE}/${KEY}.txt`,
      urlList,
    }),
  });

  console.log(`IndexNow POST ${res.status} ${res.statusText} — submitted ${urlList.length} URL(s)`);
  const text = await res.text();
  if (text) console.log(text);
  if (!res.ok && res.status !== 202) process.exit(1);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
