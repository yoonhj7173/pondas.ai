# SEO / GEO Playbook — pondas.ai

**Living doc.** 항목을 하나 다룰 때마다 → 실제 확인(코드/prod 실측) → 해당 섹션 상태·근거·다음스텝 update + 맨 아래 Changelog 한 줄 추가.

- **방법론(트랙/체크리스트/파이프라인)은 제품 무관** → Swoony(swoony.ai)에서 2026-07-02 하루에 완주하며 검증된 순서를 이식. 원본 방법론: `ai-partner/specs/seo-pipeline.md`.
- **현황(상태표의 값)은 이 인스턴스 = pondas.ai 전용.**
- 스택: Next.js 14 App Router · Clerk(auth) · Stripe · Amplitude · Pixi.js(오피스심 캔버스) · 프로드 `pondas.ai` (LIVE 2026-06-20). `NEXT_PUBLIC_SITE_URL=https://pondas.ai` (Vercel, DEPLOY.md). 코드 내부명은 "Craft"(레거시 코드네임) — 제품명은 pondas.ai.

> ⚠️ **감사 정정(2026-07-07):** 초판에서 robots/sitemap/OG이미지를 "없음"으로 오기록했으나 **셋 다 이미 존재**함(실측 실수 = zsh glob abort로 ls가 통째 abort + 리포 루트/frontend의 `app/` 중복 경로 혼동). 아래 표는 **파일별 `test -f` 재실측** 기준.

---

## How to use

진행 방식:
1. **현황 체크** — 있는지/없는지를 추측 안 하고 실제 파일·prod HTTP로 확인. (파일별로 — glob 한 방에 몰아서 확인하다 abort로 오판한 전례 있음.)
2. **품질 판단** — 있으면 형식만 갖춘 건지, 실제 최적화된 건지.
3. **다음 스텝** — 없으면 어떻게, 미흡하면 뭘 고칠지 + 우선순위·근거.

**상태 표기**: ✅ 됨·최적화됨 · 🟡 있지만 미흡(형식만/부분적) · ❌ 없음 · ⬜ 미확인

---

## 원칙 (착각 방지)

- **Lighthouse SEO 100 = 기술 기본기 통과(바닥선)이지 랭킹 능력이 아니다.** 키워드 적합성·콘텐츠 깊이·백링크·검색 수요 매칭 = 랭킹 핵심은 Lighthouse가 안 봄.
- **CWV는 필드 데이터(CrUX) 합격/불합격 판정** — LCP<2.5s · INP<200ms · CLS<0.1. lab 모바일 점수는 가혹한 시뮬(Moto G+Slow 4G+CPU 4x), 실사용과 다름.
- **팩트 기반.** "있다/최적화됐다"를 실제 파일·prod로 확인. **파일 존재는 개별 `test -f`로** (multi-glob은 하나 실패하면 전체 abort → 오판).
- **변경은 컨펌 후.** 진단·제안은 바로. 코드 수정은 승인(ㄱㄱ) 후. 배포는 "배포해" 후.
- **두 트랙 다 본다.** 전통 검색(Google/Bing)=SEO, AI 답변엔진(ChatGPT/Perplexity/AI Overviews)=GEO.
- **폐기 항목 안 함**: AMP(2021), FID(2024-03 INP 대체).

---

## 🎯 pondas 전략 차이 (Swoony 복붙 금지 지점)

**Swoony는 캐릭터 238개 = 거대한 프로그래매틱 롱테일**이 사이트맵을 채웠다. **pondas.ai는 그런 프로그래매틱 표면이 전혀 없다** — 색인 대상은 랜딩 + 블로그 + 법무뿐인 B2B/프로슈머 SaaS.

- **기술 SEO/GEO 뼈대는 이미 런치 때 상당 부분 구축됨**(robots·sitemap·OG이미지·per-route metadata·canonical·랜딩/블로그 JSON-LD·GSC verification). → 남은 건 **신설이 아니라 보강 + 소수 net-new**(Org/WebSite 스키마, llms.txt 최신화, IndexNow).
- **콘텐츠·키워드 트랙은 완전히 재설계.** 롱테일 프로그래매틱이 아니라 **fat-head 랜딩 + 비교 페이지 + 블로그 콘텐츠 마케팅**이 게임.
  - 키워드 축 후보: "AI agent team / AI company", "autonomous coding agent", "AI agents for solo founders", 경쟁사 대안("Devin / Cursor / vibe coding 대안"), "multi-agent orchestration app".
  - **블로그는 나중에 본격 가동 예정**(현재 3편). 기반 단계에서 sitemap·llms.txt·IndexNow가 **새 글을 자동 반영**하게 훅을 걸어두는 게 핵심.

---

## SEO 트랙 (Google / Bing)

### A. Technical SEO
| 항목 | 상태 | 현황 / 목표 / 다음스텝 / 근거 |
|------|------|------|
| robots.txt | ✅ | **보강 완료(P0-1, 2026-07-07)**. `*`+AI봇 8종 모두에 disallow 적용(`/app /onboarding /billing /api` + 프리뷰 4종) · sitemap+host 선언 · AI봇에 `OAI-SearchBot`·`ChatGPT-User` 추가. `/robots.txt` 렌더 실측 OK |
| sitemap.xml | ✅ | **보강 완료(P0-2, 2026-07-07)**. `/ /blog + 블로그글 + 법무 3`. 블로그 `lastModified`=frontmatter `date`, `changeFrequency` 부여. `/sitemap.xml` 렌더 실측 OK |
| 프리뷰 라우트 노출 | ✅ | `design /*-preview` 전부 `"use client"`(metadata noindex 불가) → P0-1 robots disallow로 크롤 차단 완료 |
| canonical URLs | ✅ | 홈(`app/page.tsx:15` `canonical:"/"`) · `/blog` · `/blog/[slug]` 전부 canonical 지정됨. 법무 페이지는 미확인(우선순위 낮음) |
| meta title/description | ✅🟡 | 루트 template(`%s · pondas.ai`)+metadataBase(`NEXT_PUBLIC_SITE_URL`)+GSC verification. 랜딩/블로그/법무 per-route. **카피·키워드 적합성 미평가**(랜딩="Run your AI company like a tiny office sim"). **[P3]** |
| viewport / mobile | ✅ | Next.js 14 기본 viewport 자동 주입(명시 export 불필요). Lighthouse SEO/A11y 실측은 미실시(→E) |
| manifest | ❌ | `app/manifest.*` 부재. PWA 안 하면 필수 아님 — 후순위 |
| 404 / redirects | ⬜ | soft-404, www→apex, http→https 체인 미확인 |
| GSC 등록 | 🟡 | verification 태그 있음=프로퍼티 등록됨. **sitemap 제출·색인 커버리지·노출 베이스라인 미확인**. **[P2-9]** |
| Bing Webmaster | 🟡 | Swoony 로그(7/2)에 GSC 임포트로 pondas 등록 기록 — sitemap 크롤 상태 **재확인 필요**. **[P2-9]** |

### B. Structured data (JSON-LD)
| 항목 | 상태 | 현황 / 목표 / 다음스텝 / 근거 |
|------|------|------|
| SoftwareApplication (랜딩) | ✅ | `app/page.tsx`에 SoftwareApplication(BusinessApplication, offer price 0) — 유효 형태 |
| Organization / WebSite @graph | ✅ | **완료(P1-3)**. 루트 layout에 Org(`#organization`, logo=/icon.png)+WebSite(`#website`, publisher→org) @graph. 모든 페이지에 심김. 홈 HTML 실측 OK |
| Article (블로그) | ✅ | **완료(P1-5)**. headline/description/datePublished/dateModified/image(사이트 OG)/author/publisher(@id 참조)/mainEntityOfPage/url. 블로그 HTML 실측 OK |
| Breadcrumb | ✅ | **완료(P1-5)**. Home>Blog>글 BreadcrumbList. 블로그 HTML 실측 OK |
| 유효성 (Rich Results Test) | ⬜ | 미실측. → P1 스키마 후 검증(에러 0, aggregateRating은 실평점 없으면 금지) |

### C. On-page
| 항목 | 상태 | 현황 / 목표 / 다음스텝 / 근거 |
|------|------|------|
| H1 | ✅ | 랜딩·블로그 인덱스/상세 h1 존재 |
| OG 이미지 | ✅ | **존재**(`app/opengraph-image.tsx`, ImageResponse 동적 — 로고(`app/icon.png`)+"pondas.ai"+태그라인, asset 못 읽어도 try/catch로 500 방지). Next가 OG/twitter 메타에 자동 연결 |
| 크롤러 시점 렌더링(SSR) | ⬜ | 랜딩/블로그 SSR HTML에 본문 실존 curl 미확인(랜딩은 Pixi 안 쓰고 CSS라 경량). `/app`은 인증 게이트라 무관 |
| 이미지 파이프라인 | 🟡 | next/image는 `components/marketing/shared.tsx`만. 마케팅 페이지 이미지 경량이라 Swoony 같은 임팩트 없을 듯 — 성능 실측(E) 후 판단 |
| 내부 링크 구조 | ⬜ | 홈→블로그, 블로그 상호링크 미확인 |
| URL 구조 | ✅ | `/blog/[slug]` 시맨틱 슬러그 |

### D. Content · Keywords
| 항목 | 상태 | 다음스텝 |
|------|------|------|
| 키워드 리서치·매핑 | ❌ | "AI agent team/company", "autonomous coding agent", 경쟁사 대안 축 수요 조사 + 페이지 매핑. **[P3-10]** |
| fat-head 랜딩 카피 | 🟡 | 톤 중심 카피 → 핵심 키워드 반영 재작성. **[P3-11]** |
| 비교/랜딩 페이지 | ❌ | "vs Devin/Cursor" 류 신설 후보. **[P3-11]** |
| 블로그 콘텐츠 | 🟡 | 3편. **나중에 본격 발행** — 기반 단계에선 자동 색인 훅만 준비. **[P3-11]** |

### E. Performance / CWV
| 항목 | 상태 | 다음스텝 |
|------|------|------|
| 마케팅 페이지 CWV | ⬜ | Lighthouse 모바일 베이스라인(랜딩/블로그, LCP 페이즈 분해). **[P2-8]** |
| `/app` 성능(Pixi) | N/A(SEO) | 인증 게이트=색인 대상 아님. 제품 UX 이슈는 별도 트랙 |
| CrUX / 필드 데이터 | ❌ | 저트래픽 → 없음. GSC CWV 리포트가 성적표(트래픽 쌓인 뒤) |
| AMP / FID | ❌(안 함) | 폐기 항목 — 스킵 |

---

## GEO 트랙 (AI 답변엔진)

| 항목 | 상태 | 현황 / 목표 / 다음스텝 / 근거 |
|------|------|------|
| llms.txt | ✅ | **완료(P1-4)**. `app/llms.txt/route.ts`(ISR 1h) 동적 생성 — pondas.ai 이름, 마크다운 링크, 블로그 3편 자동 등재. 정적 `public/llms.txt` 제거. 실측 OK |
| AI 크롤러 접근 허용 | ✅ | **완료(P0-1)**. GPTBot·OAI-SearchBot·ChatGPT-User·ClaudeBot·anthropic-ai·PerplexityBot·Google-Extended·CCBot 허용 + 비공개 경로는 이들에게도 disallow |
| IndexNow (Bing/Naver/Yandex push) | 🔄 | **코드 완료(P1-6)** — 키 `public/b32c...cfb.txt` + `scripts/indexnow-ping.mjs`. **활성화는 배포 후**(키 파일 prod 200 필요, 신규 키 첫 핑 403 정상)👤 |
| llms-full.txt | ❌ | 없음. 콘텐츠 볼륨 늘면 검토(후순위) |
| structured data 유효성 | ⬜ | Rich Results Test 미실측(B와 연결) |
| AI 검색 실제 노출 | ⬜ | ChatGPT/Perplexity에 "AI agent team app" 등 물었을 때 pondas 언급 여부 — 베이스라인 미측정 |

---

## 태스크 보드 (2026-07-07 수립, 정정판)

> 상태: ✅완료 · 🔄진행중 · ⬜대기 · 👤유저 액션 필요. **기반은 이미 80% 구축됨 — 아래는 보강+net-new.**

### P0 — 기존 파일 보강 (작은 편집)
- ✅ **P0-1** `app/robots.ts` 보강 — disallow에 `/billing /api` + 프리뷰 4종 추가 · AI-bot 규칙에도 동일 disallow 부여 · `OAI-SearchBot`·`ChatGPT-User` 추가. 빌드 후 `/robots.txt` 렌더 실측 OK(2026-07-07)
- ✅ **P0-2** `app/sitemap.ts` 보강 — `allSlugs`→`allPosts`, 블로그 `lastModified`=frontmatter `date` + `changeFrequency`. `/sitemap.xml` 렌더 실측 OK(글별 날짜 06-05~06-10 반영)

### P1 — net-new (구조화 데이터 + GEO)
- ✅ **P1-3** 루트 layout에 Organization + WebSite `@graph` JSON-LD 추가 — 홈 HTML 렌더 실측 OK(2026-07-07)
- ✅ **P1-4** `llms.txt` 최신화 + ISR 동적화(`app/llms.txt/route.ts`, revalidate 1h) — "Craft"→"pondas.ai", 마크다운 링크, 블로그 3편 자동 등재 실측. `public/llms.txt`(정적) 제거
- ✅ **P1-5** Article 스키마 보강(image=사이트 OG · dateModified · publisher @id 참조 · mainEntityOfPage) + Breadcrumb — 블로그 HTML 렌더 실측 OK. **Rich Results Test는 배포 후 라이브 URL로 검증 예정(⬜)**
- ✅ **P1-6** IndexNow — 키 `public/b32c41acfa97f9f77d41045346aa1cfb.txt` + `scripts/indexnow-ping.mjs`. **배포·활성화 완료(2026-07-07)**: 키 파일 prod 200, 첫 핑 **202 Accepted, 8 URL 제출**(403 없이 통과). 이후 블로그 발행 시 새 URL 인자로 재호출

### P2 — 인덱싱 / 성능 / 후순위
- ✅ **P2-8** Lighthouse 모바일 베이스라인(2026-07-07, prod). 랜딩 **Perf 76·SEO 100·A11y 93·BP 100**(FCP 1.2s·LCP 6.4s·CLS 0·TBT 30ms) / 블로그 **Perf 77·SEO 100·A11y 95·BP 100**(FCP 0.8s·LCP 5.9s·CLS 0·TBT 30ms). SEO 100·CLS 0·TBT 30ms 우수, **LCP ~6s만 lab 소프트스팟**(모바일 Slow-4G 시뮬 — 최종 판단은 CrUX 필드데이터). 스냅샷 하단
- 🔄👤 **P2-9** GSC sitemap 제출 + 노출/색인 베이스라인 · Bing sitemap 재확인 — **유저 대시보드 액션**(OAuth 필요, 헤드리스 불가). IndexNow는 이미 Bing/Naver/Yandex push 완료
- ✅ **Rich Results(라이브 파싱 검증)** — 홈/블로그 JSON-LD 전 블록 유효(Organization·WebSite·SoftwareApplication·Article·BreadcrumbList, 구문에러 0). 구글 공식 Rich Results Test 배지 미리보기는 유저가 원할 때(후순위)
- ⬜ (후순위) manifest · 404/redirect 체인 확인

### P3 — 콘텐츠/키워드 (별도 세션)
- ⬜ **P3-10** 키워드 수요 리서치 + 키워드↔페이지 매핑
- ⬜ **P3-11** fat-head 랜딩 카피 키워드화 · 비교 페이지 · 블로그 케이던스(본격 발행 시)

### 진행 순서
- **이번 세션**: P0(robots+sitemap 보강) → P1(Org/WebSite 스키마 · llms.txt · IndexNow · Article 보강)
- **다음**: P2 실측/인덱싱 → P3 콘텐츠

---

## 현황 스냅샷

### 2026-07-07 — Lighthouse 모바일 (prod, 배포 직후 P0+P1 반영)
- 랜딩(`/`): **Perf 76 · SEO 100 · A11y 93 · BP 100** — FCP 1.2s · LCP 6.4s · CLS 0 · TBT 30ms
- 블로그(`/blog/one-agent-per-desk`): **Perf 77 · SEO 100 · A11y 95 · BP 100** — FCP 0.8s · LCP 5.9s · CLS 0 · TBT 30ms
- 해석: SEO 100 = 기술 기본기 통과선(랭킹 보장 아님). CLS 0·TBT 30ms 우수. **유일한 소프트스팟 = LCP ~6s**(모바일 Slow-4G 시뮬의 워스트케이스 — 랜딩은 Pixi 없이 CSS라 실사용은 훨씬 빠를 것). 최종 판단은 트래픽 쌓인 뒤 CrUX/GSC CWV 리포트로. 성능 튜닝은 필드데이터 불합격 시 착수(현재 후순위)

## Changelog

- **2026-07-07** — **배포 + 인덱싱 활성화**. PR #38 squash 머지→main(`a25d22f`)→Vercel 자동배포(~50s 착지). 라이브 전수 검증: robots(신규 disallow+AI봇), sitemap(글별 날짜), llms.txt(pondas+블로그), 홈/블로그 JSON-LD 전 블록 파싱 유효. **IndexNow 첫 핑 202 Accepted(8 URL)**. Lighthouse 베이스라인 확보(스냅샷). 남은 유저 액션 = GSC sitemap 제출 + Bing 재확인(대시보드 OAuth 필요).
- **2026-07-07** — **P1 완료**(구조화 데이터 + GEO). 루트 layout에 Organization+WebSite @graph(P1-3). llms.txt 정적("Craft")→`app/llms.txt/route.ts` ISR 동적화, 마크다운 링크·블로그 자동 등재(P1-4). 블로그 Article 스키마 보강(image/dateModified/publisher@id/mainEntityOfPage)+Breadcrumb(P1-5). IndexNow 키+`indexnow-ping.mjs` 코드 완료(P1-6, 활성화는 배포 후). `next build` PASS·tsc 클린, 홈/블로그/llms.txt 렌더 실측 검증. 다음 = P2(Lighthouse 베이스라인·GSC/Bing sitemap 제출) + 배포 후 Rich Results Test·IndexNow 활성화.
- **2026-07-07** — **P0 완료**(robots.ts + sitemap.ts 보강). robots: `*`+AI봇 8종 disallow 통일(`/app /onboarding /billing /api`+프리뷰4) · OAI-SearchBot/ChatGPT-User 추가. sitemap: 블로그 lastmod=frontmatter date + changeFrequency(allSlugs→allPosts). `next build` PASS·tsc 클린, `/robots.txt`·`/sitemap.xml` 렌더 실측 검증. 다음 = P1(Org/WebSite @graph · llms.txt 최신화 · IndexNow · Article 보강).
- **2026-07-07** — **감사 정정 + 재수립.** 초판이 robots/sitemap/OG이미지를 "없음"으로 오기록(zsh multi-glob abort + 루트/frontend `app/` 중복으로 오판) → 파일별 `test -f` 재실측: **셋 다 존재**. 실제 상태 = 기술 SEO 뼈대 런치 때 상당 구축(robots·sitemap·OG·canonical·per-route metadata·랜딩/블로그 JSON-LD·GSC verification). 진짜 갭 = Org/WebSite @graph 부재 · llms.txt stale("Craft") · IndexNow 부재 · robots disallow 미흡(billing/api/preview) · Article 스키마 얕음. 보드를 P0(보강)~P3으로 재편.
- **2026-07-07** — 플레이북 최초 생성(초판, 위에서 정정됨).
</content>
