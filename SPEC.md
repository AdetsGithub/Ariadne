# Ariadne — Advanced Security Testing Web Scraper

**Document type:** Product & Technical Specification  
**Version:** 1.0.0  
**Status:** Draft for implementation  
**Primary stack:** Python 3.11+, Scrapy, Playwright, curl_cffi  
**Audience:** Red team / offensive security engineers operating under explicit authorization  

---

## 1. Purpose

Ariadne is an authorized-scope web reconnaissance and extraction platform built on Scrapy. It is designed for penetration testers and red team operators who need reliable, stealth-capable crawling of modern web applications protected by multi-layer anti-bot systems.

Unlike commodity scrapers optimized solely for data harvesting, Ariadne treats every crawl as a **security assessment artifact**: mapping attack surface, discovering hidden endpoints, capturing client-side API traffic, fingerprinting defenses, and producing structured evidence suitable for reports and follow-on testing.

### 1.1 Problem statement

Modern targets no longer serve useful content via naive HTTP clients. Anti-bot stacks (Cloudflare, Akamai Bot Manager, DataDome, PerimeterX/HUMAN) combine:

| Layer | What it inspects | Failure mode for naive scrapers |
| --- | --- | --- |
| IP reputation | ASN, datacenter ranges, prior abuse | Instant 403 / challenge from AWS/GCP IPs |
| TLS fingerprinting (JA3/JA4) | ClientHello cipher suites & extensions | `requests`/`urllib3` blocked before HTML |
| HTTP header heuristics | UA, `Sec-Fetch-*`, header order, Accept consistency | Easy bot classification |
| Browser fingerprinting | `navigator.webdriver`, canvas, WebGL, fonts, plugins | Stock headless Chrome detected in ms |
| Behavioral analysis | Timing, mouse/scroll, navigation graph | Fixed-interval crawlers flagged mid-session |
| JS challenges / CAPTCHAs | Turnstile, reCAPTCHA v3, hCaptcha | Non-JS clients stuck in challenge loops |
| Honeypots | Hidden links (`display:none`, white-on-white) | Blind crawlers self-incriminate |

Ariadne must defeat or gracefully degrade across these layers **within authorized engagement rules**, while remaining polite enough not to DoS the target.

### 1.2 Design principles

1. **Authorization first** — scope files, allowlists, and hard kill-switches are mandatory, not optional.
2. **Progressive fidelity** — start cheap (HTTP + TLS impersonation); escalate to fortified browsers only when needed.
3. **Layered evasion** — no single technique is sufficient; IP, TLS, headers, fingerprint, and behavior must align.
4. **Security-useful output** — crawl results are recon products (endpoints, params, tech stack, defenses), not only scraped fields.
5. **Observability** — every block, challenge, and escalation is logged for operator awareness and report evidence.
6. **Maintainability** — site layout drift and anti-bot evolution are expected; monitoring and fallback selectors are built in.

---

## 2. Scope & authorization model

### 2.1 In scope (authorized engagements)

- Public and authenticated pages within a signed ROE / bug-bounty / internal pentest scope
- Discovery of links, forms, JS-loaded routes, XHR/fetch API endpoints, and sitemap-derived URLs
- Passive and active recon extraction: headers, cookies, CSP, tech fingerprints, robots/sitemap analysis
- Controlled interaction: pagination, filters, login (with provided credentials), modal dismissal, infinite scroll
- Defense telemetry: challenge types encountered, CAPTCHA frequency, WAF signatures, rate-limit thresholds

### 2.2 Explicitly out of scope

- Unscoped third-party domains (except documented CDN/API hosts required to render in-scope apps)
- Credential stuffing, brute force, or password spraying
- Exploitation payloads, exploit PoCs, or active vulnerability weaponization
- Denial-of-service, resource exhaustion, or intentional service degradation
- Scraping / exfiltration of personal data beyond what the engagement requires and policy permits
- Impersonating Googlebot or other privileged crawlers without written authorization

### 2.3 Authorization controls (hard requirements)

| Control | Requirement |
| --- | --- |
| Scope file | YAML/JSON allowlist of domains, path prefixes, IP ranges; deny-by-default |
| Engagement metadata | Client, ticket ID, operator, start/end timestamps written into every run artifact |
| Rate ceilings | Global and per-host max concurrency and RPS; cannot be overridden without `--force-unsafe` + audit log |
| robots.txt | Configurable: `obey` (default for polite recon), `observe` (log but continue), `ignore` (requires explicit flag + justification field) |
| Kill switch | Env var / file watch / SIGTERM that drains queue and exits cleanly |
| Secrets | Credentials and proxy keys only via env / secret store; never committed |

---

## 3. Goals & non-goals

### 3.1 Goals

| ID | Goal | Success measure |
| --- | --- | --- |
| G1 | Crawl static and JS-heavy targets under authorized scope | ≥95% page success on moderate-protection sites with residential proxies |
| G2 | Survive common anti-bot stacks with progressive escalation | Automatic escalate HTTP → TLS-impersonate → stealth Playwright on challenge signals |
| G3 | Produce security-oriented crawl graphs and endpoint inventories | JSON/NDJSON export of URLs, methods, params, status codes, response fingerprints |
| G4 | Capture client-side API traffic during browser sessions | Record XHR/fetch URLs, methods, request/response samples (PII-redacted option) |
| G5 | Avoid honeypots and self-fingerprinting | Zero honeypot follows in unit/integration tests; visibility checks on links |
| G6 | Operate politely under load | Configurable delays; exponential backoff on 429/503; never ignore Retry-After by default |
| G7 | Remain operable when DOM structure drifts | Health checks / canary URLs; selector fallbacks; alert on extraction failure rate |

### 3.2 Non-goals

- Replacing commercial unlocker APIs for every hardened enterprise target (optional integration only)
- Guaranteed 100% bypass of all CAPTCHA / bot vendors
- Full AI agent natural-language browsing as primary path (may be optional Phase 3)
- General-purpose marketplace price scraping SaaS

---

## 4. Threat model (defenses Ariadne must handle)

Informed by current industry practice (2025–2026 anti-bot landscape):

### 4.1 Detection vectors

1. **IP analysis** — volume, ASN reputation, known proxy lists, geo mismatch vs `Accept-Language` / locale  
2. **TLS / JA3–JA4** — Python default stacks fingerprint as non-browser  
3. **HTTP fingerprints** — incomplete headers, wrong header order, stale User-Agents, missing `Sec-CH-UA` / `Sec-Fetch-*`  
4. **Browser automation leaks** — `navigator.webdriver`, HeadlessChrome UA, missing plugins, abnormal WebGL/canvas  
5. **Behavioral ML** — constant inter-request timing, zero mouse/scroll, deep-link entry without referrer path  
6. **Challenges** — Cloudflare Turnstile / JS challenge, reCAPTCHA v3 scores, hCaptcha, Akamai sensor cookies (`_abck`)  
7. **Honeypots** — CSS-hidden links, off-screen anchors, trap query params  
8. **Session continuity breaks** — cookie / clearance loss causing re-challenge storms  

### 4.2 Vendor profiles (reference)

| Vendor | Notable signals | Preferred Ariadne counter |
| --- | --- | --- |
| Cloudflare | Turnstile, JA4, IP score, `cf_clearance` | Stealth browser + sticky residential session; reuse clearance |
| Akamai | Client sensor JS, `_abck`, TLS cross-check | Full browser context; consistent cipher/UA pairing |
| DataDome | ASN + cadence + header entropy + JS | Mobile/residential sticky sessions; human timing |
| PerimeterX / HUMAN | Delayed enforcement via behavior | Mouse/scroll simulation; session warmup; avoid burst patterns |

---

## 5. High-level architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Operator / CI / CLI                              │
│                    ariadne crawl -c engagement.yaml                      │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────────┐
│                         Scrapy Engine (core)                             │
│  Scheduler │ Downloader │ Spider │ Item Pipeline │ Extensions            │
└─────┬──────────────┬───────────────┬──────────────────┬─────────────────┘
      │              │               │                  │
      ▼              ▼               ▼                  ▼
┌──────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐
│ Scope &  │  │ Downloader  │  │ Browser     │  │ Item Pipelines     │
│ Policy   │  │ Middlewares │  │ Pool        │  │                    │
│ Gateway  │  │             │  │ (Playwright │  │ - validate/schema  │
│          │  │ - headers   │  │  stealth)   │  │ - dedupe           │
│ robots   │  │ - TLS imp.  │  │             │  │ - endpoint invent. │
│ rate     │  │ - proxy rot │  │ - humanize  │  │ - storage exporters│
│ allow    │  │ - retry/backoff│ │ - CDP APIs │  │ - evidence pack    │
└──────────┘  └─────────────┘  └─────────────┘  └────────────────────┘
      │              │               │
      └──────────────┴───────────────┘
                     │
         ┌───────────▼───────────┐
         │  Proxy / Session Mgr  │
         │  datacenter|resi|mobile│
         │  sticky sessions      │
         └───────────────────────┘
```

### 5.1 Progressive downloader strategy

Requests flow through escalating transport modes:

| Mode | Transport | When used | Cost / detectability tradeoff |
| --- | --- | --- | --- |
| `L0_http` | Scrapy default (Twisted) | Low-protection / internal apps | Fast; weak TLS fingerprint |
| `L1_impersonate` | `curl_cffi` browser TLS impersonation | External sites with JA3/JA4 checks | Fast; strong TLS; no JS |
| `L2_browser` | Playwright + stealth patches | JS-rendered / challenge pages | Slow; high fidelity |
| `L3_unlocker` | Optional commercial unlocker API | Hardened targets after L2 fails | Highest reliability; $$ |

Escalation triggers (configurable): HTTP 403/429/503 with challenge body signatures, Cloudflare interstitial HTML, empty SPA shells, CAPTCHA iframes, DataDome deny pages, soft-block patterns (delayed empty responses).

---

## 6. Technology stack

### 6.1 Core

| Component | Library | Role |
| --- | --- | --- |
| Crawl framework | **Scrapy** ≥ 2.11 | Engine, scheduling, middleware, pipelines, concurrency |
| Async / items | itemadapter, pydantic v2 | Typed items and validation |
| HTML parse | parsel (built-in), lxml, selectolax (optional hot path) | Extraction |
| Config | PyYAML, python-dotenv | Engagement & runtime config |
| CLI | click or typer | Operator interface |
| Logging | structlog or Scrapy logging + JSON logs | Audit trail |

### 6.2 Stealth & transport

| Component | Library | Role |
| --- | --- | --- |
| TLS impersonation | **curl_cffi** | Chrome/Firefox JA3/JA4-compatible HTTP for L1 |
| Browser automation | **Playwright** (Python) | L2 JS rendering, interaction, network capture |
| Stealth | playwright-stealth / equivalent patches | Mask `webdriver` and common automation leaks |
| Optional Selenium path | undetected-chromedriver / SeleniumBase UC | Fallback for sites where Playwright is fingerprinted |
| Fingerprint profiles | curated UA + Client Hints + viewport pools | Consistent persona per session |
| Humanization | custom middleware + Playwright mouse/scroll helpers | Behavioral noise |

### 6.3 Networking & resilience

| Component | Library / approach | Role |
| --- | --- | --- |
| Proxies | Configurable providers (Bright Data, Oxylabs, etc.) + local list | Rotation; residential preferred for hardened targets |
| Retry / backoff | Scrapy Autothrottle + custom RetryMiddleware | 429/`Retry-After`, 403 rotate-and-retry |
| DNS / HTTP2 | curl_cffi / Playwright native | Match browser protocol behavior |
| Certificate handling | system trust + optional MITM unlocker paths (documented) | Correct TLS for unlocker modes |

### 6.4 Security-testing enrichments

| Component | Library | Role |
| --- | --- | --- |
| Tech fingerprint | Wappalyzer-like rules (python-Wappalyzer or custom) | Stack identification |
| URL / param analysis | urlextract, custom parsers | Parameter inventory |
| robots / sitemap | urllib.robotparser + sitemap crawler spider | Policy observation |
| Content hash | xxhash / hashlib | Change detection |
| Optional LLM extract | provider-agnostic interface | Schema extraction on messy pages (Phase 3) |

### 6.5 Storage & export

- Local: SQLite / filesystem NDJSON, HAR exports, screenshot PNGs  
- Optional: PostgreSQL, S3-compatible object store  
- Formats: JSON, CSV, Markdown summary, CycloneDX-like endpoint SBOM (custom), ZIP evidence pack  

---

## 7. Functional requirements

### 7.1 Crawl modes

| Mode | Description |
| --- | --- |
| `map` | Discover URLs only (links, sitemaps, JS route hints); minimal body storage |
| `extract` | Full extraction per spider rules / CSS/XPath / JSON-LD |
| `apisnoop` | Browser mode with network interception; inventory XHR/fetch/WebSocket endpoints |
| `auth` | Login flow then scoped crawl with session jar |
| `canary` | Periodic health checks against known selectors for drift detection |
| `passive` | Headers/cookies/CSP/tech only; no deep link follow |

### 7.2 Request authenticity (HTTP layer)

**MUST:**

1. Rotate User-Agents from a **current** browser version pool (stale UAs are themselves a signal).  
2. Emit complete browser-like headers: `Accept`, `Accept-Language`, `Accept-Encoding`, `Upgrade-Insecure-Requests`, `Sec-Fetch-*`, `Sec-CH-UA*` when claiming Chromium.  
3. Keep **UA ↔ Client Hints ↔ TLS impersonation profile** internally consistent.  
4. Set realistic `Referer` (Google locale-matched, or same-site navigation referrer).  
5. Support cookie jar persistence per sticky session (including `cf_clearance` reuse within TTL).  

**SHOULD:**

6. Randomize viewport and locale in concert with proxy geolocation.  
7. Prefer HTTP/2 when impersonating modern Chrome.  

### 7.3 Proxy & session management

**MUST:**

1. Support datacenter, residential, and mobile proxy classes with per-target policy.  
2. Rotate on hard blocks; support **sticky sessions** for challenge clearance and auth.  
3. Match proxy geo to target expectation and header locale.  
4. Retire bad proxies (consecutive failures / challenge loops) from the active pool.  
5. Never log full proxy credentials in plain logs (redact).  

### 7.4 Timing & politeness

**MUST:**

1. Randomize delays (prefer Gaussian / jittered distributions, not fixed intervals). Default inter-request mean configurable (e.g., 2–10s for sensitive targets).  
2. Honor `Retry-After` on 429.  
3. Exponential backoff with jitter on 429/503/soft-block.  
4. Integrate Scrapy Autothrottle; downshift when latency rises (intentional slowdown / overload signal).  
5. Support `Crawl-delay` from robots.txt when `robots: obey`.  

### 7.5 Browser / dynamic content (L2)

**MUST:**

1. Wait strategies: `domcontentloaded`, `networkidle`, selector-based waits, `waitForResponse` for known APIs.  
2. Infinite scroll / lazy-load helpers with randomized scroll depths and pauses.  
3. Stealth patches for common automation fingerprints.  
4. Prefer headed or `--headless=new` where stealth requires it; make mode configurable.  
5. Resource blocking (images/fonts/CSS) as an **opt-in** speed mode — disabled by default on high-stealth targets (missing resources can alter fingerprints).  
6. Persist and restore storage state (cookies + localStorage) between runs.  
7. Capture screenshots on challenge/block for evidence.  

**SHOULD:**

8. Simulate mouse movement trajectories and occasional mis-clicks / hesitation.  
9. Warm up sessions (homepage → category → deep page) instead of cold deep-linking.  
10. Multi-browser engine option (Chromium primary; Firefox/WebKit for quirk bypass).  

### 7.6 Honeypot avoidance

**MUST:**

1. Skip links with computed/inlined `display:none`, `visibility:hidden`, zero opacity, off-screen positioning when detectable.  
2. Skip common trap class names (`honeypot`, `hidden`, `invisible`, etc. — configurable).  
3. Prefer Playwright `is_visible()` in L2 over HTML-only checks.  
4. Never follow `mailto:`, `javascript:`, or out-of-scope schemes unless explicitly enabled.  

### 7.7 CAPTCHA & challenge handling

**MUST:**

1. Detect challenge pages (signature matchers for Cloudflare, DataDome, Akamai, reCAPTCHA, hCaptcha, Turnstile).  
2. Prefer **avoidance** (better IP/behavior) over solving.  
3. Pluggable solver interface (2Captcha / Anti-Captcha / CapSolver / unlocker API).  
4. After solve, keep session sticky so clearance cookies persist.  
5. Budget caps: max solves per run; alert when exceeded.  

### 7.8 Security recon outputs

Every successful (and relevant failed) response SHOULD contribute to:

| Artifact | Contents |
| --- | --- |
| URL inventory | Absolute URL, status, content-type, depth, parent URL, mode (L0–L3) |
| Endpoint inventory | API paths from HTML, JS bundles, and network capture; HTTP methods if known |
| Parameter map | Query/body/path params with example values (redaction rules applied) |
| Form catalog | action, method, input names/types, CSRF token field names |
| Header dossier | Server, powered-by, CSP, CORS, cookies flags (Secure/HttpOnly/SameSite) |
| Tech fingerprint | CMS, frameworks, CDNs, bot vendors inferred |
| Defense events | Challenge type, block code, proxy class used, escalation path |
| Diff / canary | Hash of key selectors vs baseline |

### 7.9 Prefer APIs over HTML when discovered

When network capture or static JS analysis reveals backend JSON endpoints that serve the same data as the UI:

1. Record them in the endpoint inventory.  
2. Optionally switch spider to API mode for efficiency (lower bot scrutiny, structured data).  
3. Document auth headers/tokens required; store tokens only in secret-backed session store.  

### 7.10 Site change detection

**MUST:**

1. Support canary URLs with expected selectors / min item counts.  
2. Fail health check (and alert) when extraction success rate drops below threshold.  
3. Unit-testable spider fixtures per page type (list, detail, search, login).  

---

## 8. Non-functional requirements

| Category | Requirement |
| --- | --- |
| Performance | L0/L1: hundreds of concurrent requests (proxy-limited). L2: tens of concurrent browser contexts with pool caps |
| Reliability | Idempotent retries; resume from jobdir / queue snapshot |
| Security | No secrets in repo; PII redaction hooks; TLS verification on by default |
| Portability | Linux primary; Docker image with Playwright deps |
| Observability | Structured logs, Prometheus-optional metrics (success rate, challenge rate, latency, proxy health) |
| Testability | pytest unit tests for middlewares; integration tests against local fixture servers; optional live canaries behind flag |

---

## 9. Configuration model

### 9.1 Engagement config (example schema)

```yaml
engagement:
  id: "ACME-2026-Q3-WEB"
  client: "ACME Corp"
  operator: "redteam@example.com"
  authorized_until: "2026-09-30T23:59:59Z"

scope:
  allow_domains:
    - "app.acme.example"
    - "api.acme.example"
  allow_url_regex:
    - "^https://app\\.acme\\.example/.*"
  deny_url_regex:
    - ".*/logout.*"
    - ".*/admin/delete.*"
  max_depth: 5
  respect_robots: obey   # obey | observe | ignore

crawl:
  mode: apisnoop         # map | extract | apisnoop | auth | canary | passive
  start_urls:
    - "https://app.acme.example/"
  transport:
    initial_mode: L1_impersonate
    escalate_to: [L2_browser, L3_unlocker]
  concurrency:
    max_concurrent_requests: 8
    download_delay_mean: 3.5
    download_delay_std: 1.2
  browser:
    headless: false
    stealth: true
    humanize: true
    capture_network: true
  proxies:
    class: residential
    geo: "us"
    sticky_ttl_seconds: 600
  captcha:
    provider: null         # or 2captcha | capsolver | unlocker
    max_solves: 25
  auth:
    enabled: false
    # credentials via env: ARIADNE_AUTH_USER / ARIADNE_AUTH_PASS

output:
  dir: "./artifacts/ACME-2026-Q3-WEB"
  formats: [ndjson, har, screenshots, markdown_summary]
  redact_pii: true
```

### 9.2 Runtime settings (Scrapy `settings.py` mapping)

Expose Scrapy knobs through Ariadne config: `CONCURRENT_REQUESTS`, `DOWNLOAD_DELAY`, `AUTOTHROTTLE_*`, `COOKIES_ENABLED`, `RETRY_HTTP_CODES`, custom middleware order, Playwright launch options, curl_cffi impersonation profile (e.g., `chrome131`).

---

## 10. Component specifications

### 10.1 Spiders

| Spider | Responsibility |
| --- | --- |
| `ScopeSpider` | Base class enforcing allow/deny, depth, honeypot filters |
| `MapSpider` | Link discovery + sitemap seed expansion |
| `ExtractSpider` | Rule-based field extraction (per-target YAML rules) |
| `ApiSnoopSpider` | L2 crawl with network event listeners |
| `AuthSpider` | Login sequence then handoff to Map/Extract |
| `CanarySpider` | Drift checks |

### 10.2 Middlewares (Downloader)

1. **ScopeMiddleware** — drop OOS requests early  
2. **PersonaHeadersMiddleware** — consistent header bundles  
3. **TlsImpersonateMiddleware** — L1 via curl_cffi  
4. **ProxyMiddleware** — rotate / sticky / geo  
5. **BackoffMiddleware** — 429/403/503 policy  
6. **ChallengeDetectMiddleware** — classify blocks; request escalation  
7. **PlaywrightDownloadHandler** — L2 render path  
8. **HoneypotFilterMiddleware** — filter discovered links before schedule  

### 10.3 Middlewares (Spider)

1. **LinkNormalizer** — canonicalize, strip tracking params (configurable)  
2. **JsRouteHintExtractor** — regex/AST-lite extraction of paths from JS  
3. **DefenseEventEmitter** — structured challenge events  

### 10.4 Pipelines

1. Validation (Pydantic)  
2. Deduplication  
3. PII redaction  
4. Endpoint / form / header enrichment  
5. Exporters (NDJSON, SQLite, HAR writer, evidence ZIP)  

### 10.5 Extensions

1. Engagement banner (logs authorization metadata at start)  
2. Kill-switch watcher  
3. Metrics exporter  
4. Canary scheduler  

---

## 11. Data model (core items)

```text
PageItem
  url, final_url, status, mode, depth, parent_url
  headers_subset, cookies_subset
  content_hash, scraped_at
  extraction: dict
  screenshot_path?: str
  defense_events?: list[DefenseEvent]

EndpointItem
  url, method?, source (html|js|network), auth_required?
  request_sample_redacted?, response_sample_redacted?
  content_type?, parameters: list[Param]

FormItem
  page_url, action, method, fields: list[Field]

DefenseEvent
  type (cloudflare|akamai|datadome|perimeterx|captcha|ratelimit|honeypot|unknown)
  url, status, detail, transport_mode, proxy_class, timestamp
```

---

## 12. CLI & operator UX

```bash
ariadne init engagement.yaml
ariadne validate engagement.yaml
ariadne crawl -c engagement.yaml
ariadne canary -c engagement.yaml
ariadne resume JOBDIR
ariadne report ./artifacts/ACME-2026-Q3-WEB
ariadne doctor   # browsers, proxies, solvers connectivity
```

`report` produces a Markdown summary: scope adherence, pages fetched, challenge rates, top endpoints, tech stack, recommended follow-on tests (informational only — no exploit content).

---

## 13. Testing strategy

| Layer | What |
| --- | --- |
| Unit | Header consistency, honeypot CSS detection, scope regex, backoff math, redaction |
| Integration | Local Flask/FastAPI fixture sites: static, SPA, rate-limited, honeypot, fake Cloudflare interstitial HTML |
| Contract | curl_cffi impersonation profile matches configured UA family |
| Stealth canary | Optional gated tests against public bot-detection demo pages (`nowsecure.nl`-class); never against third-party production without auth |
| Regression | Canary spiders for customer fixtures stored as HTML snapshots |

---

## 14. Implementation phases

### Phase 0 — Spec & scaffolding (this document)

- Repo layout, engagement config schema, CI skeleton  

### Phase 1 — Scrapy core + L0/L1

- Scope enforcement, persona headers, curl_cffi downloader, proxy middleware, backoff, map/extract spiders, NDJSON export  

### Phase 2 — L2 Playwright stealth + recon

- Browser pool, humanization, network capture (`apisnoop`), honeypot visibility checks, screenshots, defense event taxonomy  

### Phase 3 — Hardening & scale

- CAPTCHA solver plugins, L3 unlocker adapter, sticky clearance reuse, metrics, evidence packs, canary/drift system, Docker  

### Phase 4 — Advanced (optional)

- Multi-engine fingerprint profiles, JS bundle static analysis for routes, optional AI extraction for unstructured pages, SeleniumBase UC fallback path  

---

## 15. Acceptance criteria (MVP = end of Phase 2)

1. Given a valid engagement YAML, Ariadne refuses to crawl out-of-scope hosts.  
2. L1 requests present browser-consistent TLS + headers (validated against a JA3 echo service in tests).  
3. On JS-rendered fixture SPA, L2 extracts items that L0 cannot.  
4. Honeypot fixture links are not followed.  
5. 429 responses respect `Retry-After` and jittered exponential backoff.  
6. `apisnoop` mode emits EndpointItems from XHR traffic.  
7. Artifacts include engagement metadata and a Markdown summary.  
8. Kill-switch stops scheduling new requests within 5 seconds.  
9. No secrets committed; `ariadne doctor` checks proxy/browser readiness.  
10. Unit + integration tests pass in CI without live target dependence.

---

## 16. Risks & mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Anti-bot vendors evolve weekly | Sudden success-rate drop | Progressive modes + unlocker fallback; canary alerts |
| Stealth plugins go stale | L2 detection | Abstract stealth backend; track Playwright/Chromium versions |
| Residential proxy cost | Budget overrun | Start L0/L1; escalate only on signals; cache clearance cookies |
| Over-aggression | Accidental DoS / ROE breach | Hard rate ceilings; Autothrottle; engagement time bounds |
| Legal / ToS conflict | Engagement risk | Authorization gate; robots policy modes; operator attestation field |
| PII in artifacts | Compliance incident | Redaction pipeline; field allowlists |

---

## 17. Ethical & legal constraints (operator obligations)

Ariadne encodes technical controls, but operators remain responsible for:

1. Valid written authorization covering all target hosts and techniques used.  
2. Compliance with applicable law (e.g., CFAA interpretation, GDPR/CCPA for personal data).  
3. Minimizing collected personal data; retaining artifacts only as long as the engagement requires.  
4. Preferring official APIs or customer-provided data exports when they satisfy test objectives.  
5. Not representing traffic as a search-engine bot unless the ROE explicitly allows it.  

The default posture is **polite, scoped, reversible recon** — not maximum-aggression scraping.

---

## 18. Repository layout (target)

```text
Ariadne/
├── SPEC.md                 # this document
├── README.md
├── pyproject.toml
├── ariadne/
│   ├── __init__.py
│   ├── cli.py
│   ├── settings.py
│   ├── items.py
│   ├── spidermiddlewares/
│   ├── downloadermiddlewares/
│   ├── downloadhandlers/     # curl_cffi, playwright
│   ├── pipelines/
│   ├── extensions/
│   ├── proxies/
│   ├── stealth/
│   ├── challenges/
│   ├── spiders/
│   └── reporting/
├── engagements/              # example configs (no secrets)
├── tests/
└── docker/
```

---

## 19. Source synthesis (informing this spec)

This specification consolidates practices described in contemporary scraping / anti-bot literature:

| Source | Incorporated themes |
| --- | --- |
| [Undetectable — Web scraping methods & practices](https://undetectable.io/blog/web-scraping-methods-and-practices/) | Rate limits, CAPTCHA, IP blocks, JS-heavy sites, robots/ToS, delays, residential/mobile proxies, antidetect fingerprints, human-like behavior, scraper maintenance |
| [Browser Use — Web scraping guide 2026](https://browser-use.com/posts/web-scraping-guide-2026) | Basic vs interactive scraping, stealth as primary bottleneck, agentic multi-step workflows, CAPTCHA solving, residential geo proxies |
| [Medium — Web scraping in 2025 / bot detection](https://medium.com/@sohail_saifii/web-scraping-in-2025-bypassing-modern-bot-detection-fcab286b117d) | Ethics, IP/fingerprint/behavior/JS/TLS layers, header hygiene, proxy classes, fortified browsers, human delays/mouse, CAPTCHA options, fingerprint isolation, managed APIs |
| [ScraperAPI — 10 tips](https://www.scraperapi.com/blog/10-tips-for-web-scraping/) | IP rotation, UA & headers, random intervals, Referer, headless browsers, honeypots, change detection, CAPTCHA services, cache last-resort |
| [Browserless — Playwright scraping guide](https://www.browserless.io/blog/scraping-with-playwright-a-developer-s-guide-to-scalable-undetectable-data-extraction) | Wait strategies, scroll/lazy load, stealth plugins, viewport/UA randomization, session cookies, resource blocking tradeoffs, retries, CAPTCHA + residential trust, scale via remote browsers |
| [Bright Data — Scraping without getting blocked](https://brightdata.com/blog/web-data/web-scraping-without-getting-blocked) | Layered detection, residential/mobile vs datacenter, Sec-Fetch headers, curl_cffi TLS impersonation, stealth Playwright, Gaussian delays, CAPTCHA automation, honeypots, exponential backoff, geo matching, prefer internal APIs, vendor-specific notes (CF/Akamai/DataDome/PX) |
| [ScrapFly — Undetected ChromeDriver](https://scrapfly.io/blog/posts/web-scraping-without-blocking-using-undetected-chromedriver) | UC patches vs stock Selenium, proxy attachment limits, headed vs headless stealth tradeoffs, limits against advanced antibots, managed ASP fallbacks |

---

## 20. Open questions (resolve before Phase 2 complete)

1. Default proxy vendor adapters to ship first-party vs generic URL templates only?  
2. Is SeleniumBase UC a hard requirement or Playwright-only for MVP?  
3. Evidence retention default (days) and encryption-at-rest expectations per client?  
4. Should `robots: ignore` require dual operator attestation in the config?  
5. Minimum Chromium version matrix for CI Playwright installs?

---

## 21. Next implementation step

Upon approval of this specification, implement **Phase 1**: Scrapy project scaffolding, engagement schema validation, ScopeMiddleware, PersonaHeadersMiddleware, curl_cffi L1 handler, proxy + backoff middlewares, Map/Extract spiders, and NDJSON artifacts — with tests against local fixtures.
