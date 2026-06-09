# Ariadne — Advanced Security Testing Web Scraper

**Document type:** Product & Technical Specification  
**Version:** 1.4.1  
**Status:** Phase 1–3 shipped; Phase 4 last-mile traps specified (post-solve stagger in-tree; JS AST offload pending)  
**Primary stack:** Python 3.11+, Scrapy (asyncio reactor), Playwright, curl_cffi  
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
| HTTP/2 framing | SETTINGS frame, window sizes, pseudo-header order | TLS-ok clients still fail Akamai/CF checks |
| HTTP header heuristics | UA, `Sec-Fetch-*`, header order, Accept consistency | Easy bot classification |
| Browser fingerprinting | `navigator.webdriver`, canvas, WebGL, fonts, plugins | Stock headless Chrome detected in ms |
| Network OPSEC leaks | Host DNS / WebRTC ICE candidates bypassing proxy | Operator real IP burned despite proxy config |
| Behavioral analysis | Timing, mouse/scroll, navigation graph | Fixed-interval crawlers flagged mid-session |
| JS challenges / CAPTCHAs | Turnstile, reCAPTCHA v3, hCaptcha | Non-JS clients stuck in challenge loops |
| Honeypots | Hidden links (`display:none`, white-on-white, external CSS) | Blind L0/L1 crawlers self-incriminate |
| L1↔L2 TLS mismatch | curl_cffi spoofs JA3; Playwright emits real bundled-Chromium JA3 | Clearance cookies invalidated on handoff when majors diverge |
| Headless rendering tells | `--headless=new` font/WebGL/viewport discrepancies | Turnstile / Akamai soft-fail despite stealth patches |

Ariadne must defeat or gracefully degrade across these layers **within authorized engagement rules**, while remaining polite enough not to DoS the target.

### 1.2 Design principles

1. **Authorization first** — scope files, allowlists, and hard kill-switches are mandatory, not optional.
2. **Progressive fidelity** — start cheap (HTTP + TLS/HTTP2 impersonation); escalate to fortified browsers only when needed.
3. **Layered evasion** — no single technique is sufficient; IP, TLS, HTTP/2, headers, fingerprint, and behavior must align.
4. **Session coherence** — L1↔L2 handoff shares one persona (UA, Client Hints, cookies, proxy sticky ID); clearance cookies are worthless without matching fingerprints.
5. **Playwright Chromium is the TLS anchor (when L2 enabled)** — `curl_cffi` can spoof any JA3; Playwright cannot. Session Sync MUST only select impersonation profiles whose `chromium_major` matches Playwright’s bundled Chromium. UA / Client Hints are derived from that anchored profile — never the reverse, and never rotated across majors during an L2-capable engagement.
6. **Non-blocking escalation** — L1→L2 never holds a Scrapy downloader slot waiting on the Browser Pool; escalate by re-scheduling into the engine queue.
7. **One solver per session** — Session Sync mutex ensures a single in-flight WAF solve per `session_id` (no thundering herd).
8. **Staggered sibling wake-ups** — after clearance is acquired, waiting siblings MUST NOT burst simultaneously; apply fresh-window jitter/stagger (§5.3.3).
9. **Split pool timeouts** — checkout **queue** timeout (acquire a context) is separate from **execution** timeout (CAPTCHA/solve hold). Never apply the queue timeout to the whole L2 task.
10. **OPSEC by default** — DNS and WebRTC must not leak the operator host IP through any transport.
11. **Bounded network capture** — `apisnoop` MUST enforce `MAX_BODY_SIZE`; oversize XHR/fetch bodies are dropped after recording URL/method/headers.
12. **Headed stealth in containers** — prefer full headed Chromium; Docker MUST provide Xvfb (`xvfb-run`) so headed mode works without a physical display.
13. **No L3 Franken-sessions** — clearance from a commercial unlocker is bound to the vendor’s IP/UA/JA3. Sessions that reach L3 are `locked_to_mode=L3` and MUST NOT de-escalate to L1/L2 with those cookies.
14. **CAPTCHA injection strategies** — solver plugins return tokens *and* target-specific submit strategies (form / JS callback / click); generic textarea injection is insufficient.
15. **Circuit breaker on drift** — sustained empty extractions trip the breaker, drain the queue, and exit critically (no alert spam / bandwidth burn).
16. **Script-friendly evidence encryption** — `ariadne pack --encrypt` uses an explicit recipient public key file (`--pubkey`) and prefers `age` over host GPG keyrings.
17. **Offload CPU-bound JS analysis** — large bundle regex/AST MUST NOT run on the reactor thread (§10.3.1).
18. **Security-useful output** — crawl results are recon products (endpoints, params, tech stack, defenses), not only scraped fields.
19. **Conditional evidence** — heavy artifacts (HAR, screenshots) only on challenges, errors, auth transitions, or explicit `apisnoop`.
20. **Observability** — every block, challenge, and escalation is logged for operator awareness and report evidence.
21. **Maintainability** — site layout drift and anti-bot evolution are expected; monitoring and fallback selectors are built in.

---

## 2. Scope & authorization model

### 2.1 In scope (authorized engagements)

- Public and authenticated pages within a signed ROE / bug-bounty / internal pentest scope
- Discovery of links, forms, JS-loaded routes, XHR/fetch API endpoints, and sitemap-derived URLs
- Passive and active recon extraction: headers, cookies, CSP, tech fingerprints, robots/sitemap analysis
- Controlled interaction: pagination, filters, login (with provided credentials), modal dismissal, infinite scroll
- Defense telemetry: challenge types encountered, CAPTCHA frequency, WAF signatures, rate-limit thresholds
- Extraction of `robots.txt` `Disallow` / `Allow` paths as **high-value recon hints** (see §2.3)

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
| robots.txt | **Default: `observe`** — parse and log rules, promote `Disallow` paths into the endpoint inventory as high-value candidates, but **do not block** crawling. Modes: `observe` (default), `obey` (polite / ToS-sensitive engagements), `ignore` (skip fetch entirely). No dual-attestation nag for `ignore`. |
| Kill switch | Env var / file watch / SIGTERM that drains queue and exits cleanly |
| Secrets | Credentials and proxy keys only via env / secret store; never committed |

#### 2.3.1 The robots.txt paradox (red team rationale)

For commodity scrapers, `obey` is polite. For security testing it is often an **anti-pattern**: developers routinely hide staging APIs, admin panels, and sensitive routes behind `Disallow`. Obeying blinds the operator to high-value attack surface.

**Default behavior (`observe`):**

1. Fetch and parse `robots.txt` / sitemaps when present.  
2. Emit `RobotsHintItem` entries for every `Disallow` / interesting `Allow` path (scoped to allowlisted hosts).  
3. Continue crawling those paths subject to normal scope + rate rules.  
4. Record that the path was robots-disallowed in artifacts for the report (transparency to the client).

Use `obey` only when the ROE or client explicitly requires crawl-delay / disallow compliance.

---

## 3. Goals & non-goals

### 3.1 Goals

| ID | Goal | Success measure |
| --- | --- | --- |
| G1 | Crawl static and JS-heavy targets under authorized scope | ≥95% page success on moderate-protection sites with residential proxies |
| G2 | Survive common anti-bot stacks with progressive escalation | Automatic escalate HTTP → TLS/H2-impersonate → stealth Playwright on challenge signals |
| G3 | Produce security-oriented crawl graphs and endpoint inventories | JSON/NDJSON export of URLs, methods, params, status codes, response fingerprints |
| G4 | Capture client-side API traffic during browser sessions | Record XHR/fetch URLs, methods, request/response samples (PII-redacted option) |
| G5 | Avoid honeypots and self-fingerprinting | Zero honeypot follows in tests; L1 unverified links deferred or risk-scored |
| G6 | Operate politely under load | Configurable delays; exponential backoff on 429/503; never ignore Retry-After by default |
| G7 | Remain operable when DOM structure drifts | Health checks / canary URLs; selector fallbacks; alert on extraction failure rate |
| G8 | Preserve session coherence across L1↔L2 | Clearance cookies acquired in L2 remain valid when traffic returns to L1 |
| G9 | No host IP leakage via DNS/WebRTC | Proxy-forced DNS; WebRTC disabled; leak canary tests pass |
| G10 | Escalate without starving L0/L1 concurrency | Challenge storms free downloader slots via re-schedule; L1 traffic continues |
| G11 | Single WAF solve per session | Concurrent challenges for one `session_id` coalesce behind a session mutex |
| G12 | Fingerprint internal consistency | When L2 enabled, every persona matches Playwright Chromium major; no cross-major rotation |
| G13 | L1↔L2 TLS coherence | Clearance acquired in L2 remains valid under L1 curl_cffi with the same major |
| G14 | CAPTCHA solves do not starve the pool | Queue timeout ≠ execution timeout; long solver polls do not kill mid-solve via checkout TTL |
| G15 | apisnoop memory safety | Bodies over `MAX_BODY_SIZE` never buffered into the Scrapy worker |
| G16 | Headed stealth in Docker | Container entrypoint uses Xvfb; Playwright `headless=false` by default for stealth engagements |
| G17 | No L3 Franken-sessions | Sessions locked to L3 after unlocker solve; no cookie reuse on L1/L2 |
| G18 | CAPTCHA token actually submits | Injection strategy plugins succeed on fixture Turnstile/reCAPTCHA flows |
| G19 | Drift stops the crawl | Circuit breaker trips on sustained empty extractions; engine drains and exits critical |
| G20 | Encrypt without GPG keyring hell | `pack --encrypt --pubkey file.asc` (or age recipient) works in Docker/CI without `~/.gnupg` |
| G21 | No post-solve micro-herd | Sibling wake-ups after clearance are staggered within the fresh window |
| G22 | Reactor stays responsive under JS analysis | Heavy JS path extraction never blocks AsyncioSelectorReactor |

### 3.2 Non-goals

- Replacing commercial unlocker APIs for every hardened enterprise target (optional integration only)
- Guaranteed 100% bypass of all CAPTCHA / bot vendors
- Full AI agent natural-language browsing as primary path (may be optional Phase 4)
- General-purpose marketplace price scraping SaaS
- First-party vendor SDKs for every proxy provider (generic HTTP(S) proxies only for MVP)
- Dual browser automation stacks (Playwright-only for MVP; no SeleniumBase UC in Phase 1–2)

---

## 4. Threat model (defenses Ariadne must handle)

Informed by current industry practice (2025–2026 anti-bot landscape):

### 4.1 Detection vectors

1. **IP analysis** — volume, ASN reputation, known proxy lists, geo mismatch vs `Accept-Language` / locale  
2. **TLS / JA3–JA4** — Python default stacks fingerprint as non-browser  
3. **HTTP/2 fingerprinting** — SETTINGS parameters, `INITIAL_WINDOW_SIZE`, stream priorities, and pseudo-header ordering (`:method`, `:authority`, `:scheme`, `:path`) must match the claimed browser; Akamai and Cloudflare validate this **in addition to** TLS  
4. **HTTP header fingerprints** — incomplete headers, wrong header order, stale User-Agents, missing `Sec-CH-UA` / `Sec-Fetch-*`  
5. **Browser automation leaks** — `navigator.webdriver`, HeadlessChrome UA, missing plugins, abnormal WebGL/canvas  
6. **DNS / WebRTC leaks** — browser resolves DNS or gathers ICE candidates on the host NIC, exposing the operator IP despite an HTTP proxy  
7. **Behavioral ML** — constant inter-request timing, zero mouse/scroll, deep-link entry without referrer path  
8. **Challenges** — Cloudflare Turnstile / JS challenge, reCAPTCHA v3 scores, hCaptcha, Akamai sensor cookies (`_abck`)  
9. **Honeypots** — CSS-hidden links (inline **or** external stylesheet / JS-applied), off-screen anchors, trap query params  
10. **Session continuity breaks** — cookie / clearance loss, or clearance reused under a **different** JA3/UA than the solving session  
11. **L1↔L2 fingerprint divergence** — curl_cffi spoofs Chrome N while Playwright’s binary is Chrome M; WAFs bind clearance to the solving fingerprint  
12. **Headless detection** — `--headless=new` still fails Turnstile/Akamai canvas, font, and WebGL probes that headed+Xvfb passes  

### 4.2 Vendor profiles (reference)

| Vendor | Notable signals | Preferred Ariadne counter |
| --- | --- | --- |
| Cloudflare | Turnstile, JA4, HTTP/2 frame fingerprint, IP score, `cf_clearance` | Stealth browser + sticky residential session; Session Sync before L1 reuse |
| Akamai | Client sensor JS, `_abck`, TLS **and** HTTP/2 cross-check | Full browser context; curl_cffi profile with matching H2 SETTINGS + UA |
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
│              Scrapy Engine (AsyncioSelectorReactor ONLY)                 │
│  Scheduler │ Downloader │ Spider │ Item Pipeline │ Extensions            │
└─────┬──────────────┬───────────────┬──────────────────┬─────────────────┘
      │              │               │                  │
      ▼              ▼               ▼                  ▼
┌──────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐
│ Scope &  │  │ Downloader  │  │ Browser     │  │ Item Pipelines     │
│ Policy   │  │ Middlewares │  │ Pool (L2)   │  │                    │
│ Gateway  │  │             │  │ long-lived  │  │ - validate/schema  │
│          │  │ - headers   │  │ contexts    │  │ - dedupe           │
│ robots   │  │ - TLS+H2    │  │ + checkout  │  │ - endpoint invent. │
│ observe  │  │ - proxy/DNS │  │   manager   │  │ - conditional I/O  │
│ rate     │  │ - escalate  │  │ - humanize  │  │ - evidence pack    │
└──────────┘  └──────┬──────┘  └──────┬──────┘  └────────────────────┘
                     │                │
                     └────────┬───────┘
                              ▼
              ┌───────────────────────────────┐
              │   Session Synchronization     │
              │   Service (shared state)      │
              │   persona · cookies · proxy   │
              │   sticky ID · clearance TTL   │
              └───────────────┬───────────────┘
                              ▼
              ┌───────────────────────────────┐
              │   Proxy / DNS Policy Layer    │
              │   datacenter|resi|mobile      │
              │   proxy-DNS · no WebRTC       │
              └───────────────────────────────┘
```

### 5.1 Mandatory asyncio reactor (scaffolding requirement)

Scrapy’s default Twisted reactor and Playwright/`curl_cffi` asyncio APIs do not mix cleanly. **Ariadne MUST run exclusively on:**

```python
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
```

This is non-negotiable from Phase 1 scaffolding onward. All custom download handlers that call asyncio libraries MUST use Scrapy’s asyncio bridge (`deferred_from_coro` / install patterns documented for Scrapy ≥ 2.11) and MUST NOT block the event loop with synchronous Playwright or long CPU work.

**Acceptance for scaffolding:** `ariadne doctor` fails closed if the asyncio reactor is not active.

### 5.2 Browser Pool (L2) — long-lived contexts, not per-request browsers

Spinning up a new Chromium + context per request is too slow and burns fingerprints. L2 uses a **pool of long-lived browser contexts**:

| Property | Requirement |
| --- | --- |
| Process model | One (or few) Playwright browser process(es); many isolated `BrowserContext`s |
| Checkout | Async context manager: `async with pool.checkout(session_id) as ctx:` |
| Binding | Each context bound to a Session Sync persona + sticky proxy for its lifetime |
| Concurrency cap | Hard max checked-out contexts (config); excess requests wait or stay on L1 |
| Isolation | No cookie/localStorage bleed across different `session_id`s |
| Deadlock avoidance | Checkout timeouts; never hold Scrapy downloader slots while waiting unbounded; release on cancel/errback |
| Recycling | Contexts recycled after N pages, idle TTL, or clearance invalidation |
| Root browser recycle | After **MaxContextsServed** (e.g. 5,000) on a Chromium process: spawn a second browser, route new checkouts there, drain old contexts, then `browser.close()` the drained process (Chromium process-level leak mitigation) |
| Graceful teardown | `BrowserPoolExtension` MUST handle `engine_stopped` and trap SIGINT/SIGTERM to `await browser.close()` on all pooled browsers **before** the asyncio reactor finalizes — prevents zombie Chromium after cancelled runs |
| Scheduler interaction | Download handler awaits checkout with **queue timeout** only for requests **already** marked `meta['transport_mode']=L2`; never block an L1 slot awaiting pool capacity (see §5.5) |

#### 5.2.1 Split timeouts — queue vs execution (CAPTCHA pool exhaustion)

Third-party CAPTCHA solvers (Turnstile, DataDome) often take **45–120+ seconds** of API polling. An L2 context blocked on a solver occupies one pool slot for the entire duration.

If `checkout_timeout` (e.g. 60s) is applied to the **whole** L2 task:

1. Concurrent solves on different domains fill the pool.  
2. Waiting Scrapy L2 requests time out, re-schedule, and storm.  
3. Worse: the solver may be killed mid-poll when the timeout fires on the holding context.

**MUST separate:**

| Timeout | Setting (example) | Meaning |
| --- | --- | --- |
| **Queue / checkout timeout** | `checkout_timeout_seconds: 60` / `ARIADNE_BROWSER_CHECKOUT_TIMEOUT` | Max wait to **acquire** a free context from the semaphore |
| **Execution timeout** | `execution_timeout_seconds: 180` / `ARIADNE_BROWSER_EXECUTION_TIMEOUT` | Max lifetime **after** acquire (navigation + CAPTCHA solve + sync) |

On queue timeout: re-schedule the L2 request at high priority (§5.5) — do not hold a downloader slot.  
On execution timeout: release challenge lock as `failed`, free the context, re-schedule or escalate per policy.

Pool lifecycle is owned by a Scrapy extension started in `spider_opened` and torn down in `spider_closed` / `engine_stopped`.

### 5.3 Session Synchronization Service

Progressive escalation fails in practice when L1 and L2 do not share state. A dedicated **Session Synchronization Service** is the source of truth for:

| Field | Purpose |
| --- | --- |
| `session_id` | Stable ID tying sticky proxy + persona + cookie jar |
| `persona` | Derived from the **TLS-anchored** catalog profile (§5.3.2 / §7.2): profile id, UA, Client Hints, locale, timezone, viewport, `chromium_major` |
| `cookie_jar` | Normalized cookie store (incl. `cf_clearance`, `_abck`, etc.) |
| `proxy_endpoint` | Sticky proxy URL / session tag |
| `clearance_meta` | How clearance was obtained (L2), TTL estimate, last validated |
| `tls_profile` / `h2_profile` | Impersonation id — **identical** to the persona’s source `curl_cffi` profile and Playwright Chromium major |
| `challenge_state` | `idle` \| `solving` \| `solved` \| `failed` — gates concurrent escalations |
| `challenge_lock` | Per-`session_id` async mutex / exclusive lease for WAF solves |
| `locked_to_mode` | `None` \| `L3_unlocker` (extensible) — when set, all subsequent fetches for this session MUST use that transport; de-escalation forbidden |

**Handoff rules (MUST):**

1. On L1 challenge → escalate to L2 **with the same `session_id`** via **non-blocking re-schedule** (§5.5), never by awaiting L2 inside the L1 downloader slot.  
2. Before starting an L2 solve, acquire the session **challenge lock** (§5.3.1).  
3. L2 solves challenge using that session’s persona + sticky proxy.  
4. L2 writes cookies / storage state back to Session Sync before releasing the lock and marking `challenge_state=solved`.  
5. Subsequent L1 requests for that `session_id` load the synced jar and **identical** profile-derived UA / Client Hints / TLS+H2 impersonation.  
6. If persona and clearance fingerprints diverge, invalidate clearance and re-escalate (do not silently send mismatched L1 traffic).  
7. **Proxy burn / IP bind:** Clearance cookies (`cf_clearance`, `_abck`, etc.) are bound to the client IP. If the sticky proxy is burned (repeated TCP timeouts, instant 403s without a JS challenge body, provider soft-ban), Session Sync MUST: drop clearance cookies + storage state → rotate sticky proxy endpoint → **keep the same persona/profile** → set `challenge_state=idle` → force full L2 re-escalate on the next request for that `session_id`. Never reuse clearance on a new IP.  
8. **L3 lock:** If a request is fulfilled by an L3 unlocker, set `locked_to_mode=L3_unlocker` and do **not** merge vendor clearance cookies into a jar intended for L1/L2 reuse (§5.4.1).  

Without this service, `cf_clearance` acquired in Playwright is invalidated the moment `curl_cffi` resumes with a different JA3/UA.

#### 5.3.1 Session challenge mutex (thundering herd prevention)

If N concurrent L1 requests share `session_id_A` and all hit Cloudflare Turnstile, a naive design escalates all N to L2 — burning CAPTCHA budget, looping challenges on the same sticky IP, and racing `set_cookies` writes.

**MUST:**

1. `try_begin_challenge(session_id) -> bool` — atomically transitions `idle|failed → solving` and grants the lock to exactly one waiter; returns `false` if already `solving`.  
2. The lock holder is the **only** request allowed to checkout an L2 context for solving that session’s WAF.  
3. Sibling requests that lose the race MUST **re-schedule** with jittered delay (`meta['waiting_for_clearance']=True`), free their downloader slot, and retry L1 after `challenge_state` becomes `solved` (or re-compete if `failed`). On wake, they MUST apply **post-solve stagger** (§5.3.3) so they do not fire as a simultaneous burst.  
4. Lock lease has a TTL (configurable, e.g. 120s); expired leases auto-fail to `failed` so the crawl cannot deadlock.  
5. Cookie jar writes during `solving` are exclusive to the lock holder; others must not mutate clearance cookies.  

```text
L1 × N hit challenge for session_A
        │
        ▼
 try_begin_challenge(A)?
   │              │
  yes             no
   │              │
   ▼              ▼
 re-schedule     re-schedule with delay
 escalate_to=L2  waiting_for_clearance=True
 (single solve)  (poll / retry L1 after solved + stagger)
```

#### 5.3.2 Playwright Chromium TLS anchor (L1↔L2 fingerprint reality gap)

**The trap:** `curl_cffi` can impersonate arbitrary browser builds (`chrome120` … `chrome133`). **Playwright cannot.** It uses a physical bundled Chromium binary and emits that binary’s real JA3/HTTP/2 fingerprint. If Session Sync picks `chrome120` for L1 while Playwright ships Chromium 131, L2 solves under Chrome-131 TLS and L1 resumes under Chrome-120 TLS — Akamai/Cloudflare invalidate clearance immediately.

**MUST (when L2 / Browser Pool is enabled):**

1. At startup, detect Playwright’s bundled Chromium **major** version (`ariadne doctor`, Session Sync extension).  
2. Filter `profiles.yaml` to profiles whose `chromium_major` **exactly equals** that major.  
3. Refuse to create sessions if no catalog profile matches (fail closed with a clear error — do not silently fall back to a mismatched major).  
4. Derive UA, `Sec-CH-UA*`, and viewport **from** the anchored profile.  
5. Do **not** rotate across Chromium majors during an L2-capable engagement. “Rotation” means choosing among sticky sessions that all claim the **same** major (e.g. different sticky proxies), not different Chrome versions.  
6. Profiles with `l2_compatible: false` (e.g. Firefox) are L1-only and MUST be excluded from the pool when L2 is enabled.  
7. When Playwright upgrades (e.g. to Chrome 133), the catalog MUST gain a matching `chrome133` curl_cffi profile before L2 engagements proceed.

**When L2 is disabled (L1-only map/extract):** the full catalog (including Firefox) may be used; TLS anchor filtering is not required.

#### 5.3.3 Post-solve sibling stagger (micro-herd prevention)

**The trap:** The challenge mutex prevents N simultaneous L2 solves. When the lock holder releases `challenge_state=solved`, all N−1 siblings waiting with `waiting_for_clearance=True` can evaluate “solved” in the same reactor tick and fire full L1 GETs from one residential sticky IP in the same millisecond — tripping DataDome cadence / Cloudflare rate limits and burning the fresh clearance.

**MUST:**

1. Record `clearance_solved_at` when transitioning to `solved`.  
2. While clearance age is within `ARIADNE_CLEARANCE_FRESH_WINDOW` (default **5s**), each waking sibling MUST delay before the L1 fetch.  
3. Delay policy (configurable): either `stagger_base * sibling_wake_index` (capped at `stagger_max`) **or** uniform jitter in `[stagger_base, stagger_max]` (default **0.5s–5.0s** jitter).  
4. Delay MUST free/yield the event loop (`asyncio.sleep` / Deferred) — never busy-wait.  
5. After the fresh window, siblings may proceed without stagger (clearance is no longer “hot”).  
6. `sibling_wake_index` resets on each new solve epoch (`clearance_epoch` bump).

```text
solve → challenge_state=solved, clearance_solved_at=now
        │
        ▼
 siblings wake (waiting_for_clearance)
        │
        ▼
 age < fresh_window?
   yes → sleep(stagger) → L1 GET
   no  → L1 GET immediately
```

### 5.4 Progressive downloader strategy

Requests flow through escalating transport modes:

| Mode | Transport | When used | Cost / detectability tradeoff |
| --- | --- | --- | --- |
| `L0_http` | Scrapy HTTP via asyncio reactor | Low-protection / internal apps | Fast; weak TLS/H2 fingerprint |
| `L1_impersonate` | `curl_cffi` browser TLS **and** HTTP/2 impersonation | External sites with JA3/JA4/H2 checks | Fast; strong wire fingerprint; no JS |
| `L2_browser` | Playwright pool + stealth | JS-rendered / challenge pages | Slow; high fidelity |
| `L3_unlocker` | Optional commercial unlocker API | Hardened targets after L2 fails | Highest reliability; $$ |

Escalation triggers (configurable): HTTP 403/429/503 with challenge body signatures, Cloudflare interstitial HTML, empty SPA shells, CAPTCHA iframes, DataDome deny pages, soft-block patterns (delayed empty responses).

De-escalation (L2 → L1) is allowed **only** after Session Sync confirms clearance + persona coherence **and** `locked_to_mode` is unset.

#### 5.4.1 L3 unlocker Franken-session trap

Commercial unlockers (Bright Data Web Unlocker, ScraperAPI, etc.) negotiate TLS and solve WAFs on **vendor infrastructure**. Returned HTML may include clearance cookies bound to the **vendor’s** IP, UA, and JA3 — not Ariadne’s residential sticky session or curl_cffi/Playwright anchor.

**MUST NOT:**

1. Write L3-acquired clearance cookies into the Session Sync jar and then de-escalate to L1 or L2.  
2. Assume `cf_clearance` from an unlocker response is portable to Ariadne transports.

**MUST:**

1. On first successful L3 fetch for a `session_id`, set `session.locked_to_mode = "L3_unlocker"`.  
2. All subsequent requests for that session force `transport_mode=L3_unlocker` (SessionSyncMiddleware / ChallengeDetect honor the lock).  
3. To leave L3: **burn** the session (drop cookies/storage, clear `locked_to_mode`) and create a fresh `session_id` / sticky proxy — never transplant unlocker cookies onto L1/L2.  
4. Store unlocker-only cookie jars separately if needed for L3 sticky vendor sessions; never mix with L1/L2 jars.  
5. Log a `DefenseEvent` of type `l3_lock` when the lock engages.

### 5.5 Non-blocking escalation (concurrency starvation fix)

Scrapy’s `CONCURRENT_REQUESTS` limits **in-flight downloader slots**. If ChallengeDetect awaits Browser Pool checkout inside the L1 response path, a challenge storm fills every slot with waiters and **starves all remaining L0/L1 work**.

**MUST NOT:** block a downloader slot while waiting for an L2 context.

**MUST (escalation algorithm):**

1. `ChallengeDetectMiddleware.process_response` classifies a challenge on an L0/L1 response.  
2. Emit a `DefenseEvent`; call `try_begin_challenge(session_id)` when a solve is needed.  
3. Build a **new** `Request` (or clone) with:
   - `meta['transport_mode'] = 'L2_browser'` (or `L3_unlocker`)
   - `meta['escalate_from'] = prior mode`
   - `meta['session_id']` unchanged
   - `dont_filter=True` **or** fingerprint includes mode (§5.6) so the DupeFilter does not drop it
   - **`priority` MUST be elevated** (default `ARIADNE_ESCALATION_PRIORITY=100`, configurable) — **not optional**. Deep Scrapy queues (tens of thousands of L1 URLs) will otherwise bury the L2 solve until after `challenge_lease_ttl` expires, breaking the mutex and deadlocking clearance waiters. Sibling `waiting_for_clearance` retries MUST use the same high priority (or a dedicated high-priority / LIFO path) so they run inside the lease window.  
4. **Yield / return the new Request** to the engine (via `Response.request` replacement patterns or errback/callback that schedules it — implementation may use `scrapy.Request` returned from middleware where supported, or spider callback re-schedule; the invariant is: **drop the current download and free the slot**).  
5. Do **not** call Playwright or `pool.checkout()` from L1 middleware. Only the L2 download handler, on an already-scheduled L2 request, may checkout.  
6. If `try_begin_challenge` returns `false`, re-schedule the **same URL** as L1 (or a lightweight “wait”) with `waiting_for_clearance=True`, **high priority**, and short delay — still freeing the slot.  

Pool saturation on genuine L2 traffic: L2 download handler uses **queue** checkout timeout; on timeout, re-schedule the L2 request with **high priority** + delay (again freeing the slot) rather than waiting unbounded. CAPTCHA/solve work after acquire is bounded by **execution** timeout (§5.2.1), not the queue timeout.

### 5.6 Request fingerprinting & deduplication

Escalating L1 → L2 requests the **same URL twice**. Scrapy’s default `RFPDupeFilter` fingerprints method + URL + body and **silently drops** the L2 retry.

**MUST** implement `ariadne.dupefilters.TransportAwareDupeFilter` (or equivalent) such that:

| Approach | Rule |
| --- | --- |
| Preferred | Include `transport_mode` (and optionally `session_id` for auth-bound URLs) in the request fingerprint hash |
| Required fallback | Escalation-scheduled requests set `dont_filter=True` |

Also treat `waiting_for_clearance` retries as intentionally repeatable: either `dont_filter=True` or a fingerprint salt (`clearance_epoch` from Session Sync) so post-solve L1 fetches are not dropped.

`DUPEFILTER_CLASS` MUST be set in scaffolding settings; tests MUST prove an L2 escalate of a seen L1 URL is not discarded.

---

## 6. Technology stack

### 6.1 Core

| Component | Library | Role |
| --- | --- | --- |
| Crawl framework | **Scrapy** ≥ 2.11 | Engine, scheduling, middleware, pipelines, concurrency |
| Event loop | **AsyncioSelectorReactor** (mandatory) | Compatible bridge for Playwright / curl_cffi |
| Async / items | itemadapter, pydantic v2 | Typed items and validation |
| HTML parse | parsel (built-in), lxml, selectolax (optional hot path) | Extraction |
| Config | PyYAML, python-dotenv | Engagement & runtime config |
| CLI | click or typer | Operator interface |
| Logging | structlog or Scrapy logging + JSON logs | Audit trail |

### 6.2 Stealth & transport

| Component | Library | Role |
| --- | --- | --- |
| TLS + HTTP/2 impersonation | **curl_cffi** | Chrome/Firefox JA3/JA4 **and** H2 SETTINGS/pseudo-header profiles for L1 |
| Browser automation | **Playwright** (Python) only for MVP | L2 JS rendering, interaction, network capture |
| Stealth | playwright-stealth / equivalent patches | Mask `webdriver` and common automation leaks |
| Fingerprint profiles | `stealth/profiles.yaml` with `chromium_major` + `l2_compatible` | When L2 on: Playwright Chromium major anchors allowed profiles; UA/CH derived from match |
| Humanization | custom helpers on pooled contexts | Behavioral noise |
| Session Sync | in-process service; optional Redis later | Shared jar/persona; TLS-anchor filter at init |
| Container stealth | Docker + **Xvfb** (`xvfb-run`) | Headed Chromium without a physical display |

> **Out of MVP:** Selenium, undetected-chromedriver, SeleniumBase UC. A single browser stack keeps Phase 2 surface area manageable. Revisit only in Phase 4 if Playwright stealth is insufficient for specific targets.

### 6.3 Networking & resilience

| Component | Library / approach | Role |
| --- | --- | --- |
| Proxies | **Generic HTTP(S) proxy URLs** via env (`ARIADNE_PROXY_URL` / list). No first-party Bright Data/Oxylabs SDKs in MVP — operators format `user:pass@host:port` (incl. provider session/geo tags in username) | Rotation; residential preferred for hardened targets |
| DNS via proxy | L1: curl_cffi / proxy CONNECT behavior; L2: proxy with remote DNS (e.g. SOCKS5h or Chromium `--dns-prefetch` disabled + proxy that resolves remotely). Never fall back to host DNS for in-scope traffic | Prevent DNS leaks |
| WebRTC | Disabled in all L2 launch args / policies | Prevent ICE candidate IP leaks |
| Retry / backoff | Scrapy Autothrottle + custom RetryMiddleware | 429/`Retry-After`, 403 rotate-and-retry |
| Certificate handling | system trust + optional MITM unlocker paths (documented) | Correct TLS for unlocker modes |

### 6.4 Security-testing enrichments

| Component | Library | Role |
| --- | --- | --- |
| Tech fingerprint | Wappalyzer-like rules (python-Wappalyzer or custom) | Stack identification |
| URL / param analysis | urlextract, custom parsers | Parameter inventory |
| robots / sitemap | urllib.robotparser + sitemap crawler | **Observe** mode + `RobotsHintItem` extraction |
| Content hash | xxhash / hashlib | Change detection |
| Optional LLM extract | provider-agnostic interface | Schema extraction on messy pages (Phase 4) |

### 6.5 Storage & export (I/O-aware)

Default artifacts are **lightweight**:

- NDJSON page/endpoint/form/defense streams  
- Optional SQLite index  
- Markdown summary via `ariadne report`  

**Conditional / expensive artifacts** (HAR, full-page screenshots, storage-state dumps) are captured **only** when:

1. A challenge / block / CAPTCHA page is detected (debug + evidence), or  
2. Mode is explicitly `apisnoop` (network HAR for API inventory), or  
3. An error or state transition occurs (auth success/fail, clearance obtained/lost), or  
4. Operator sets `output.capture: always` (discouraged; warn on large scopes).  

### 6.5 Storage & export (I/O-aware)

Default artifacts are **lightweight**:

- NDJSON page/endpoint/form/defense streams  
- Optional SQLite index  
- Markdown summary via `ariadne report`  

**Conditional / expensive artifacts** (HAR, full-page screenshots, storage-state dumps) are captured **only** when:

1. A challenge / block / CAPTCHA page is detected (debug + evidence), or  
2. Mode is explicitly `apisnoop` (network HAR for API inventory), or  
3. An error or state transition occurs (auth success/fail, clearance obtained/lost), or  
4. Operator sets `output.capture: always` (discouraged; warn on large scopes).  

Ephemeral local storage is the default. Client delivery:

```bash
# Prefer age (script-friendly). Explicit pubkey file — NO host GPG keyring / pinentry.
ariadne pack ./artifacts/ENGAGEMENT --encrypt --pubkey recipient.age
# Or ASCII-armored recipient key for age/GPG-compatible workflows:
ariadne pack ./artifacts/ENGAGEMENT --encrypt --pubkey recipient.asc
```

**MUST NOT** require `~/.gnupg`, interactive `pinentry`, or ambient default-key selection inside Docker/CI. Cryptography UX is file-in / file-out. Preferred implementation: **`age`** via `pyrage` (or CLI `age`); optional GPG only when `--pubkey` points at a public key file and `--batch`/`--trust-model always` avoids prompts.

---

## 7. Functional requirements

### 7.1 Crawl modes

| Mode | Description |
| --- | --- |
| `map` | Discover URLs only (links, sitemaps, JS route hints, robots Disallow hints); minimal body storage |
| `extract` | Full extraction per spider rules / CSS/XPath / JSON-LD |
| `apisnoop` | Browser mode with network interception; inventory XHR/fetch/WebSocket; **enables HAR** |
| `auth` | Login flow then scoped crawl with session jar via Session Sync |
| `canary` | Periodic health checks against known selectors for drift detection |
| `passive` | Headers/cookies/CSP/tech only; no deep link follow |

### 7.2 Request authenticity (HTTP layer) & persona generation

**Persona source of truth — reverse dependency with Playwright TLS anchor:**

You cannot pick a random User-Agent and ask `curl_cffi` to match it. Impersonation profiles are **pre-compiled** browser builds. A Chrome 126 UA with a Chrome 124 TLS/H2 stack is an instant Akamai/CF inconsistency kill.

**Further:** when L2 is enabled, even a coherent curl_cffi profile is wrong if it does not match Playwright’s **physical** Chromium major (§5.3.2). Playwright cannot spoof JA3/H2; L1 must claim what L2 actually is.

1. At startup with L2 enabled: detect Playwright Chromium major; filter catalog to `chromium_major == that major`.  
2. Enumerate remaining **supported** `curl_cffi` impersonation profile IDs (`ariadne doctor` / Session Sync).  
3. Session Sync selects from the **anchored** set only (typically a single major; sticky per session).  
4. **Derive** from that profile: exact User-Agent, `Sec-CH-UA` / `Sec-CH-UA-Mobile` / `Sec-CH-UA-Platform`, Accept-Language, viewport.  
5. L1 always calls `impersonate=<that profile id>`. L2 Playwright contexts use the **same** derived UA and viewport.  
6. Do not invent UAs outside the catalog. Do not rotate across Chromium majors while L2 is enabled.  
7. When `curl_cffi` or Playwright adds/removes builds, update `profiles.yaml`; CI / `ariadne doctor` fails if no profile matches the installed Chromium major.  

**Additional MUST:**

8. Emit complete browser-like headers consistent with the derived persona: `Accept`, `Accept-Language`, `Accept-Encoding`, `Upgrade-Insecure-Requests`, `Sec-Fetch-*`.  
9. Set realistic `Referer` (Google locale-matched, or same-site navigation referrer).  
10. Support cookie jar persistence per sticky session via Session Sync.  
11. L1 impersonation MUST apply the profile’s TLS **and** HTTP/2 fingerprint — not TLS alone.  

**SHOULD:**

12. Align locale/timezone with proxy geo when the sticky proxy encoding supports it.  
13. Fail contract tests if observed JA3/H2 characteristics diverge from the selected profile’s expectations.  
14. `ariadne doctor` prints Playwright major and the list of L1↔L2-compatible profiles.  

### 7.3 Proxy, DNS & OPSEC

**MUST:**

1. Support datacenter, residential, and mobile proxy classes via generic proxy URL templates (class inferred from operator config, not vendor SDK).  
2. Rotate on hard blocks; support **sticky sessions** for challenge clearance and auth (sticky ID stored in Session Sync).  
3. Match proxy geo to target expectation and header locale when the proxy URL encoding supports it.  
4. Retire bad proxies (consecutive failures / challenge loops) from the active pool.  
5. Never log full proxy credentials in plain logs (redact).  
6. **Force DNS resolution through the proxy path** for L1 and L2. Host-resolver bypass is a defect.  
7. **Disable WebRTC** (and related STUN) in L2 launch arguments / Chromium policies so ICE candidates cannot expose the operator IP.  
8. Provide a `ariadne doctor --leak-check` (or test fixture) that fails if WebRTC/DNS leak the host address when a proxy is configured.  

### 7.4 Timing & politeness

**MUST:**

1. Randomize delays (prefer Gaussian / jittered distributions, not fixed intervals). Default inter-request mean configurable (e.g., 2–10s for sensitive targets).  
2. Honor `Retry-After` on 429.  
3. Exponential backoff with jitter on 429/503/soft-block.  
4. Integrate Scrapy Autothrottle; downshift when latency rises (intentional slowdown / overload signal).  
5. Honor `Crawl-delay` from robots.txt **only** when `respect_robots: obey`.  

### 7.5 Browser / dynamic content (L2)

**MUST:**

1. Serve pages from the Browser Pool (§5.2), not one-shot browser launches per request.  
2. Wait strategies: `domcontentloaded`, `networkidle`, selector-based waits, `waitForResponse` for known APIs.  
3. Infinite scroll / lazy-load helpers with randomized scroll depths and pauses.  
4. Stealth patches for common automation fingerprints.  
5. **Prefer headed mode** (`headless: false`) for stealth engagements. Cloudflare Turnstile and Akamai Bot Manager frequently flag `--headless=new` via font, WebGL, and boot-viewport discrepancies.  
6. **Docker / headless servers:** when no physical display exists, run under **Xvfb** so Playwright remains headed. Container entrypoint MUST wrap the crawl: `xvfb-run -a ariadne crawl ...` (see §8 / `docker/`). Do not silently force `headless=true` in Docker without an explicit engagement override.  
7. Resource blocking (images/fonts/CSS) as an **opt-in** speed mode — disabled by default on high-stealth targets (missing resources can alter fingerprints).  
8. Persist and restore storage state through Session Sync (cookies + localStorage).  
9. Capture screenshots **conditionally** (§6.5) — challenges, errors, auth transitions — not every page.  
10. Apply DNS-via-proxy + WebRTC-disabled launch config on every browser/context (§7.3).  
11. Honor **execution timeout** (§5.2.1) for the full L2 task after context acquire; never reuse the queue timeout for solve duration.  

**SHOULD:**

12. Simulate mouse movement trajectories and occasional mis-clicks / hesitation.  
13. Warm up sessions (homepage → category → deep page) instead of cold deep-linking.  
14. Multi-browser engine option post-MVP (Chromium primary; Firefox/WebKit for quirk bypass) — only if a matching curl_cffi profile and TLS story exist.  

### 7.6 Honeypot avoidance

**MUST:**

1. Skip links with computed/inlined `display:none`, `visibility:hidden`, zero opacity, off-screen positioning when detectable.  
2. Skip common trap class names (`honeypot`, `hidden`, `invisible`, etc. — configurable).  
3. Prefer Playwright `is_visible()` (computed style) in L2 over HTML-only checks.  
4. Never follow `mailto:`, `javascript:`, or out-of-scope schemes unless explicitly enabled.  

**L0/L1 visibility gap (MUST address):**

Static HTML cannot evaluate styles applied via external CSS or JavaScript. A naive L1 crawler will follow honeypots that L2 would skip.

| Policy | Behavior |
| --- | --- |
| `honeypot.l1_unverified: defer` (default) | Queue unverifiable links to an **L2 validation queue**; only schedule for full crawl after visibility confirmation (or drop if invisible) |
| `honeypot.l1_unverified: risk_score` | Assign risk score from heuristics (suspicious classes, odd URL patterns, no anchor text, etc.); follow only below threshold |
| `honeypot.l1_unverified: follow` | Aggressive; log warning — not recommended |

Inline-style / obvious trap heuristics still apply on L1 before deferral.

### 7.7 CAPTCHA & challenge handling

**MUST:**

1. Detect challenge pages (signature matchers for Cloudflare, DataDome, Akamai, reCAPTCHA, hCaptcha, Turnstile).  
2. Prefer **avoidance** (better IP/behavior) over solving.  
3. Pluggable solver interface (2Captcha / Anti-Captcha / CapSolver / unlocker API).  
4. Escalate via **non-blocking re-schedule** (§5.5); never await L2 inside an L1 downloader slot.  
5. Enforce **one in-flight solve per `session_id`** via Session Sync challenge mutex (§5.3.1).  
6. After solve, write clearance into Session Sync, set `challenge_state=solved`, release lock, keep sticky proxy + TLS-anchored persona.  
7. Budget caps: max solves per run; alert when exceeded.  
8. On de-escalate to L1, verify profile/TLS/H2 still match the solving session and Playwright Chromium major (§5.3 / §5.3.2).  
9. Sibling requests waiting on clearance MUST NOT open additional L2 contexts for the same session.  
10. Solver API polling MUST run inside an already-checked-out context bounded by **execution timeout** (≥ typical solver latency, e.g. 180s), not the **checkout queue timeout** (§5.2.1).  

#### 7.7.1 Token injection strategies (not just token fetch)

Retrieving a solve token from 2Captcha/CapSolver is ~20% of the work. Modern Turnstile / reCAPTCHA often will not accept a naive form POST. They require injecting the token into a hidden field and invoking a **dynamically named, minified** JS callback (e.g. paths under `___grecaptcha_cfg.clients[...]`) or clicking a specific element.

**MUST** define a pluggable `InjectionStrategy` on the solver plugin interface:

| Strategy | Method | When |
| --- | --- | --- |
| Form submit | `inject_and_submit_form(page, token, field_selector, form_selector)` | Classic hidden-input + form submit |
| JS callback | `inject_and_trigger_callback(page, token, callback_name \| callback_resolver)` | reCAPTCHA/Turnstile client callbacks |
| Click | `inject_and_click_element(page, token, field_selector, click_selector)` | Custom UI that unlocks on button click after token set |

**MUST NOT** assume a single generic DOM injection works across targets. Target-specific strategy configs (YAML/engagement) select which method runs after the token API returns. Strategies run inside L2 under the execution timeout.

### 7.8 Security recon outputs & apisnoop memory bounds

Every successful (and relevant failed) response SHOULD contribute to:

| Artifact | Contents |
| --- | --- |
| URL inventory | Absolute URL, status, content-type, depth, parent URL, mode (L0–L3) |
| Endpoint inventory | API paths from HTML, JS bundles, and network capture; HTTP methods if known |
| Robots hints | `Disallow`/`Allow` paths promoted as recon candidates (`observe` mode) |
| Parameter map | Query/body/path params with example values (redaction rules applied) |
| Form catalog | action, method, input names/types, CSRF token field names |
| Header dossier | Server, powered-by, CSP, CORS, cookies flags (Secure/HttpOnly/SameSite) |
| Tech fingerprint | CMS, frameworks, CDNs, bot vendors inferred |
| Defense events | Challenge type, block code, proxy class used, escalation path, session_id |
| Diff / canary | Hash of key selectors vs baseline |

Heavy blobs (HAR, PNG) follow conditional capture rules (§6.5).

#### 7.8.1 `apisnoop` OOM guard (`MAX_BODY_SIZE`)

Playwright `page.on('response')` buffers bodies into the Python process. A SPA that serves a 20MB source map or 50MB JSON blob, across concurrent browsers and hundreds of pages, will OOM the Scrapy worker.

**MUST:**

1. Default `ARIADNE_MAX_BODY_SIZE` = **2 MiB** (configurable).  
2. On each intercepted XHR/fetch/response: if `Content-Length` (or actual body length) exceeds the limit, record URL, method, status, content-type, and selected headers into `EndpointItem`, set `body_truncated=true`, and **drop** the body.  
3. Never retain truncated payloads in HAR/export beyond the size cap.  
4. Unit/integration tests prove oversized fixtures do not increase process RSS unboundedly (or at least that bodies are not attached to items).  

### 7.9 Prefer APIs over HTML when discovered

When network capture or static JS analysis reveals backend JSON endpoints that serve the same data as the UI:

1. Record them in the endpoint inventory.  
2. Optionally switch spider to API mode for efficiency (lower bot scrutiny, structured data).  
3. Document auth headers/tokens required; store tokens only in Session Sync / secret-backed store.  

### 7.10 Site change detection & circuit breaker

**MUST:**

1. Support canary URLs with expected selectors / min item counts.  
2. Fail health check when extraction success rate drops below threshold.  
3. Unit-testable spider fixtures per page type (list, detail, search, login).  

#### 7.10.1 Circuit breaker (alert fatigue / bandwidth burn)

A UI/XPath drift can yield thousands of HTTP 200 pages with **empty** extractions. Logging every failure spams operators and burns engagement proxy budget.

**MUST** implement `CircuitBreakerMiddleware` (or extension):

| Parameter | Default | Meaning |
| --- | --- | --- |
| `window` | 50 | Consecutive L0/L1 (or all-mode) responses evaluated |
| `empty_ratio_threshold` | 0.50 | Trip when ≥50% of window have empty/failed extraction |
| `min_samples` | 20 | Do not trip before enough samples |

**On trip:**

1. Emit a single critical `DefenseEvent` / log (`circuit_breaker_trip`).  
2. Pause scheduling new requests; gracefully **drain** in-flight work.  
3. Close the spider / engine with reason `extraction_drift` (non-zero exit).  
4. Do **not** continue crawling or spam per-page alerts after the trip.

Canary mode (§7.1) remains for proactive light checks; the circuit breaker protects full crawls from silent hollow success.

---

## 8. Non-functional requirements

| Category | Requirement |
| --- | --- |
| Performance | L0/L1: hundreds of concurrent requests (proxy-limited). L2: capped concurrent **checked-out** contexts from the pool. `CONCURRENT_REQUESTS` may exceed pool size; escalation must not couple them |
| Event loop | No blocking calls on the asyncio reactor; Playwright work must be awaited; challenge waits must be re-schedules, not in-slot sleeps |
| Reliability | Idempotent retries; resume from jobdir / queue snapshot; Session Sync durable for run lifetime; challenge lock leases expire |
| Pool timeouts | Queue timeout ≠ execution timeout; execution ≥ typical CAPTCHA solver latency (§5.2.1) |
| Memory | `apisnoop` enforces `MAX_BODY_SIZE` (default 2 MiB); no unbounded response-body buffering (§7.8.1) |
| Disk I/O | Default NDJSON-only; HAR/screenshots conditional to avoid multi-GB exhaustion on large maps |
| Security / OPSEC | No secrets in repo; PII redaction; TLS verify on; DNS/WebRTC leak protections |
| Portability | Linux primary; Docker image with Playwright deps, fonts, and **Xvfb**; entrypoint `xvfb-run` for headed stealth (§7.5) |
| Observability | Structured logs, optional Prometheus (success/challenge/latency, pool wait, body truncations, browser recycles) |
| Testability | pytest; fixtures; leak-check; Chromium-anchor filter tests; H2/TLS contract tests |

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
  respect_robots: observe   # observe (default) | obey | ignore

crawl:
  mode: apisnoop         # map | extract | apisnoop | auth | canary | passive
  start_urls:
    - "https://app.acme.example/"
  transport:
    initial_mode: L1_impersonate
    escalate_to: [L2_browser, L3_unlocker]
    # When L2 is enabled, Session Sync IGNORES this list unless entries match
    # Playwright's Chromium major (TLS anchor). Prefer omitting and letting
    # the catalog auto-select the anchored profile.
    impersonate_profiles: null
  concurrency:
    max_concurrent_requests: 8
    download_delay_mean: 3.5
    download_delay_std: 1.2
  session:
    challenge_lease_ttl_seconds: 120
    clearance_wait_delay_mean: 2.0
    escalation_priority: 100       # mandatory high priority for L2 + clearance waiters
  browser:
    headless: false                # prefer headed; use Xvfb in Docker
    stealth: true
    humanize: true
    capture_network: true          # apisnoop / conditional HAR
    pool_size: 4                   # max concurrent BrowserContexts
    checkout_timeout_seconds: 60   # QUEUE wait to acquire a context
    execution_timeout_seconds: 180 # HOLD time after acquire (CAPTCHA solves)
    max_contexts_served: 5000      # recycle root Chromium process after this many contexts
    disable_webrtc: true           # mandatory default
    proxy_dns: true                # mandatory when proxy set
    max_body_size_bytes: 2097152   # 2 MiB apisnoop OOM guard
  honeypot:
    l1_unverified: defer       # defer | risk_score | follow
  proxies:
    # Generic URL(s); provider geo/session tags encoded in userinfo by operator
    # e.g. http://user-country-us-session-abc:pass@proxy.example:8080
    class: residential
    sticky_ttl_seconds: 600
  captcha:
    provider: null             # or 2captcha | capsolver | unlocker
    max_solves: 25
  auth:
    enabled: false
    # credentials via env: ARIADNE_AUTH_USER / ARIADNE_AUTH_PASS

output:
  dir: "./artifacts/ACME-2026-Q3-WEB"
  formats: [ndjson, markdown_summary]   # har/screenshots are conditional by default
  capture:
    screenshots: on_challenge_or_error  # never | on_challenge_or_error | always
    har: on_apisnoop_or_challenge       # never | on_apisnoop_or_challenge | always
  redact_pii: true
```

Proxy credentials via env, e.g. `ARIADNE_PROXY_URL` or `ARIADNE_PROXY_LIST_FILE` — not committed YAML secrets.

### 9.2 Runtime settings (Scrapy `settings.py` mapping)

**MUST set in scaffolding:**

```python
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
```

Also expose: `CONCURRENT_REQUESTS`, `DOWNLOAD_DELAY`, `AUTOTHROTTLE_*`, `COOKIES_ENABLED` (jar ultimately owned by Session Sync), `RETRY_HTTP_CODES`, middleware order, Playwright launch options, `DUPEFILTER_CLASS = "ariadne.dupefilters.TransportAwareDupeFilter"`, `ARIADNE_BROWSER_POOL_SIZE`, `ARIADNE_BROWSER_CHECKOUT_TIMEOUT`, `ARIADNE_BROWSER_EXECUTION_TIMEOUT`, `ARIADNE_MAX_BODY_SIZE`, `ARIADNE_BROWSER_HEADLESS`, challenge lease TTL.

> Note: Raising `CONCURRENT_REQUESTS` above Browser Pool size is expected and safe **because** escalation re-schedules instead of awaiting checkout in-slot. Pool size caps only true L2 parallelism, not total crawl concurrency. CAPTCHA solves consume a pool slot for up to `execution_timeout`, so size the pool for concurrent domains under challenge — not for solver latency alone.

---

## 10. Component specifications

### 10.1 Spiders

| Spider | Responsibility |
| --- | --- |
| `ScopeSpider` | Base class enforcing allow/deny, depth, honeypot policy |
| `MapSpider` | Link discovery + sitemap seed expansion + robots hint ingestion |
| `ExtractSpider` | Rule-based field extraction (per-target YAML rules) |
| `ApiSnoopSpider` | L2 crawl with network event listeners |
| `AuthSpider` | Login sequence then handoff via Session Sync |
| `CanarySpider` | Drift checks |

### 10.2 Middlewares (Downloader)

1. **ScopeMiddleware** — drop OOS requests early  
2. **SessionSyncMiddleware** — attach `session_id`, load profile-derived persona + cookies onto request meta; if `waiting_for_clearance` and state still `solving`, re-schedule with delay (free slot)  
3. **PersonaHeadersMiddleware** — header bundles from Session Sync persona (never ad-hoc UAs)  
4. **TlsHttp2ImpersonateHandler** — L1 via curl_cffi using `persona.impersonate_id`  
5. **ProxyMiddleware** — rotate / sticky / geo; enforce proxy-DNS policy  
6. **BackoffMiddleware** — 429/403/503 policy  
7. **ChallengeDetectMiddleware** — classify blocks; on L0/L1 challenge: `try_begin_challenge` → **yield re-scheduled L2 (or wait) Request** and drop current response path (§5.5); never `await pool.checkout()` here  
8. **PlaywrightPoolDownloadHandler** — runs **only** for requests already at `transport_mode=L2`; checkout pool; lock holder performs solve; sync cookies; release challenge lock  
9. **HoneypotFilterMiddleware** — filter / defer unverified L1 links  

### 10.2.1 Escalation control flow (normative)

```text
L1 response → ChallengeDetect
    │
    ├─ not challenge → pass through
    │
    └─ challenge
         ├─ try_begin_challenge(session)?
         │     yes → schedule Request(url, mode=L2, dont_filter/mode-aware fingerprint)
         │           return/drop to FREE downloader slot
         │     no  → schedule Request(url, mode=L1, waiting_for_clearance, delay)
         │           return/drop to FREE downloader slot
         │
L2 request (later) → PlaywrightPoolDownloadHandler
         → checkout context → solve → SessionSync.set_cookies
         → challenge_state=solved → release lock → return Response
```

### 10.3 Middlewares (Spider)

1. **LinkNormalizer** — canonicalize, strip tracking params (configurable)  
2. **JsRouteHintExtractor** — regex/AST-lite extraction of paths from JS (**MUST** offload CPU — §10.3.1)  
3. **RobotsHintEmitter** — promote Disallow paths to inventory under `observe`  
4. **DefenseEventEmitter** — structured challenge events  

#### 10.3.1 JsRouteHintExtractor — reactor offload (event-loop starvation)

**The trap:** Modern JS bundles are often 5–20 MB of minified code. Regex or AST-lite parsing over such payloads can take hundreds of milliseconds of CPU. Scrapy’s single Python thread + `AsyncioSelectorReactor` means that work inside a spider middleware **stalls** in-flight downloads, Playwright IPC, and timers — cascading timeouts across the crawl.

**MUST:**

1. Never run heavy JS path extraction synchronously on the reactor/middleware call stack.  
2. Copy or hand off the JS body to a worker via `asyncio.to_thread` or a bounded `ProcessPoolExecutor`.  
3. Yield control back to the reactor while the future runs; when complete, emit `EndpointItem`s / follow Requests.  
4. Cap input size (e.g. skip or sample beyond a configured max bytes) so pathological bundles cannot monopolize the pool.  
5. Prefer process pool for true parallelism on multi-core hosts when AST parsing is CPU-heavy; thread pool is acceptable for lighter regex passes that release the GIL poorly.

### 10.4 Pipelines

1. Validation (Pydantic)  
2. Deduplication  
3. PII redaction  
4. Endpoint / form / header / robots-hint enrichment  
5. Exporters (NDJSON, optional SQLite; conditional HAR/screenshot writers)  

### 10.5 Extensions

1. Engagement banner (logs authorization metadata at start)  
2. **AsyncioReactorGuard** — abort if wrong reactor  
3. **BrowserPoolExtension** — start/stop pool; **MUST** close all Playwright browsers on `engine_stopped` and on SIGINT/SIGTERM before reactor teardown (no zombie Chromium); recycle root browser after MaxContextsServed; expose separate checkout vs execution timeouts  
4. **SessionSyncExtension** — process-lifetime session store; detect Playwright Chromium major and filter profiles (TLS anchor); expose `burn_proxy(session_id)` for sticky-IP death → drop clearance → rotate proxy → re-escalate  
5. Kill-switch watcher  
6. Metrics exporter (include pool wait time, escalation counts, challenge-lock waiters, re-schedule rate, browser process recycles, body truncations)  
7. Canary scheduler  

### 10.6 DupeFilter

| Component | Responsibility |
| --- | --- |
| `TransportAwareDupeFilter` | Fingerprint includes `transport_mode` (+ optional `clearance_epoch`); configured as `DUPEFILTER_CLASS` |

Escalation paths MUST still set `dont_filter=True` as belt-and-suspenders during Phase 1 until fingerprint tests are green.

### 10.7 Session Synchronization Service (API sketch)

```text
# Persona factory (profile → headers); when L2 on, filter by Playwright chromium_major
list_impersonate_profiles(allowlist=None, chromium_major=None, require_l2_anchor=False) -> list[ProfileMeta]
create_persona_from_profile(profile_id) -> Persona
detect_playwright_chromium_major() -> int | None

get_or_create(session_id | host) -> Session
bind_persona(session, persona)          # persona must reference a known profile_id
get_cookies(session) / set_cookies(session, cookies)
get_storage_state(session) / set_storage_state(...)
invalidate_clearance(session, reason)
assert_coherent(session) -> bool        # profile_id ↔ UA ↔ TLS/H2 ↔ cookies

# Challenge mutex
try_begin_challenge(session_id, lease_ttl) -> bool
release_challenge(session_id, state: solved|failed)
get_challenge_state(session_id) -> idle|solving|solved|failed
clearance_epoch(session_id) -> int      # bumped on each successful solve; salts dupe fingerprints

# Proxy burn (IP-bound clearance)
burn_sticky_proxy(session_id, reason) -> Session
  # drops clearance + storage; rotates proxy endpoint; keeps persona;
  # challenge_state=idle; next fetch must L2 re-escalate
```

### 10.8 Profile metadata catalog

Ship `ariadne/stealth/profiles.yaml` mapping each supported `curl_cffi` profile id → canonical UA, Client Hints, default viewport, **`chromium_major`**, and **`l2_compatible`**. Session Sync refuses personas that are not in this catalog. When L2 is enabled, only profiles with matching `chromium_major` and `l2_compatible: true` are selectable (§5.3.2).

### 10.9 Docker / Xvfb

| Artifact | Requirement |
| --- | --- |
| `docker/Dockerfile` | Playwright base image + `xvfb` + liberation/noto fonts |
| `docker/entrypoint.sh` | `xvfb-run -a --server-args="-screen 0 1920x1080x24" "$@"` when `ARIADNE_USE_XVFB=1` (default) |
| Default browser mode in image | `ARIADNE_BROWSER_HEADLESS=false` |

Operators may set `ARIADNE_USE_XVFB=0` and `headless: true` only when ROE accepts reduced stealth.
---

## 11. Data model (core items)

```text
PageItem
  url, final_url, status, mode, depth, parent_url, session_id
  headers_subset, cookies_subset
  content_hash, scraped_at
  extraction: dict
  screenshot_path?: str          # only if conditionally captured
  har_path?: str                 # only if conditionally captured
  defense_events?: list[DefenseEvent]

EndpointItem
  url, method?, source (html|js|network|robots), auth_required?
  request_sample_redacted?, response_sample_redacted?
  content_type?, parameters: list[Param]

RobotsHintItem
  host, path, directive (disallow|allow), crawl_decision (followed|skipped_obey)

FormItem
  page_url, action, method, fields: list[Field]

DefenseEvent
  type (cloudflare|akamai|datadome|perimeterx|captcha|ratelimit|honeypot|leak|unknown)
  url, status, detail, transport_mode, proxy_class, session_id, timestamp
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
ariadne pack ./artifacts/ACME-2026-Q3-WEB --encrypt --pubkey recipient.age
ariadne doctor              # reactor, browsers, TLS anchor, proxies
ariadne doctor --leak-check # DNS/WebRTC leak canary + WebRTC launch-arg check
```

`report` produces a Markdown summary: scope adherence, pages fetched, challenge rates, robots hints followed, top endpoints, tech stack, recommended follow-on tests (informational only — no exploit content).

---

## 13. Testing strategy

| Layer | What |
| --- | --- |
| Unit | Profile→persona derivation, honeypot deferral, scope regex, backoff, redaction, Session Sync coherence + mutex, fingerprint includes transport_mode |
| Integration | Local fixtures: static, SPA, rate-limited, honeypot (external CSS), fake Cloudflare interstitial; L1→L2→L1 clearance reuse |
| Concurrency | Challenge storm: N>L2-pool L1 challenges must not stall unrelated L0/L1 requests; assert downloader slot frees on escalate |
| Thundering herd | N concurrent challenges for one `session_id` → exactly one L2 solve; others wait/re-schedule |
| DupeFilter | L2 escalate of a previously seen L1 URL is not dropped |
| Contract | Catalog profile IDs ⊆ curl_cffi supported set; derived UA matches profile metadata; `chromium_major` present for L2 profiles |
| TLS anchor | With mocked Playwright major M, Session Sync only emits profiles where `chromium_major == M`; missing match fails closed |
| Pool timeouts | Unit tests assert `checkout_timeout` ≠ `execution_timeout` and CAPTCHA-length tasks are not killed by queue TTL |
| apisnoop OOM | Oversized fixture responses yield `body_truncated=true` EndpointItems without attaching full bodies |
| Reactor | Boot fails/tests fail if AsyncioSelectorReactor not installed |
| Pool | Checkout timeout re-schedules (no unbounded wait); no cross-session cookie bleed; engine_stopped closes browsers |
| OPSEC | Leak-check: with proxy set, WebRTC/DNS must not expose host IP; launch args include `--disable-webrtc` |
| Stealth canary | Optional gated tests against public bot-detection demos; never against third-party production without auth |
| I/O | Assert HAR/screenshots absent on normal `map` crawl; present on challenge fixture |
| Docker | Image build installs Xvfb; entrypoint documentation requires `xvfb-run` for headed mode |

---

## 14. Implementation phases

### Phase 0 — Spec & scaffolding

- Repo layout, engagement config schema, **AsyncioSelectorReactor** wired, CI skeleton  

### Phase 1 — Scrapy core + L0/L1

- Scope enforcement, Session Sync (in-process) with profile→persona factory + challenge mutex stubs, TransportAwareDupeFilter, persona headers, curl_cffi TLS+H2 handler, generic proxy middleware (DNS-safe), backoff, robots `observe` + hints, map/extract spiders, NDJSON export, L1 honeypot deferral stubs, **non-blocking escalate re-schedule skeleton** (even before real L2)  

### Phase 2 — L2 Playwright pool + recon ✅

- Browser Pool + checkout manager with **split queue/execution timeouts**
- Playwright Chromium **TLS anchor** gating Session Sync profiles
- WebRTC disabled + proxy DNS; humanization; headed default + **Xvfb Docker**
- Network capture (`apisnoop`) with **`MAX_BODY_SIZE`** truncation
- Session Sync L1↔L2 handoff with mutex; challenge-storm concurrency tests
- Honeypot visibility validation queue; conditional screenshots; defense event taxonomy

### Phase 3 — Hardening & scale ✅

- CAPTCHA solver plugins with **InjectionStrategy** (form / callback / click), respecting execution timeout  
- L3 unlocker adapter with **`locked_to_mode`** (no Franken-sessions)  
- **CircuitBreakerMiddleware** on extraction drift  
- `ariadne pack --encrypt --pubkey` (age-preferred; no GPG keyring)  
- Metrics hooks; Docker/Xvfb already from Phase 2  

### Phase 4 — Advanced (optional)

- Multi-engine fingerprint profiles; optional AI extraction; SeleniumBase UC **only if** Playwright path proven insufficient for a documented target class  
- **JsRouteHintExtractor** with **reactor offload** (`asyncio.to_thread` / process pool) — §10.3.1  
- Post-solve sibling stagger is **already normative** (§5.3.3) and implemented with Phase 3 ship  

---

## 15. Acceptance criteria (MVP = end of Phase 2)

1. Given a valid engagement YAML, Ariadne refuses to crawl out-of-scope hosts.  
2. Process runs on `AsyncioSelectorReactor`; `ariadne doctor` detects misconfiguration.  
3. With L2 enabled, every session persona matches Playwright’s Chromium major; inventing a UA / selecting a mismatched major is impossible via public APIs.  
4. L1 requests present browser-consistent TLS **and** HTTP/2 fingerprints for that anchored profile (contract tests).  
5. On JS-rendered fixture SPA, L2 extracts items that L0/L1 cannot.  
6. L1→L2 challenge solve → L1 reuse succeeds on fixture **only when** Session Sync keeps profile+cookies+major coherent; mismatched major/persona test fails closed.  
7. Browser Pool reuses contexts; per-request browser launch is not the default path.  
8. **Concurrency:** with `CONCURRENT_REQUESTS=16` and `pool_size=4`, a synthetic challenge storm on many URLs does not prevent unrelated non-challenge L1 requests from completing (escalation frees slots via re-schedule).  
9. **Thundering herd:** N concurrent challenges for one `session_id` result in exactly one L2 solve attempt; siblings wait on clearance.  
9a. **Post-solve micro-herd:** after solve, N siblings do not fire L1 in the same millisecond; stagger applies within the fresh window (§5.3.3).  
10. **DupeFilter:** re-scheduled L2 request for a URL already fetched at L1 is not silently dropped.  
11. **Split timeouts:** a simulated 90s CAPTCHA hold does not fail solely because `checkout_timeout=60`; execution timeout governs the hold.  
12. **apisnoop OOM:** a >`MAX_BODY_SIZE` XHR fixture yields an EndpointItem with `body_truncated=true` and no full body attached.  
13. **Headed/Xvfb:** Docker entrypoint documents/uses `xvfb-run`; default `headless=false` for stealth.  
14. Honeypot fixture with **external CSS** is not followed from L1 without L2 validation (defer policy).  
15. With proxy configured, leak-check passes (no host IP via WebRTC/DNS).  
16. 429 responses respect `Retry-After` and jittered exponential backoff.  
17. `apisnoop` emits EndpointItems from XHR; HAR exists for that mode when configured; normal `map` does not write per-page HAR/PNG.  
18. `respect_robots: observe` records `RobotsHintItem`s and still crawls Disallow paths in scope.  
19. Kill-switch stops scheduling new requests within 5 seconds; BrowserPool closes on engine stop (no zombie Chromium in tests).  
20. `ariadne pack --encrypt` produces a client-deliverable archive (Phase 3 may complete encryption; Phase 2 at least documents the command).  
21. Unit + integration tests pass in CI without live target dependence.  

---

## 16. Risks & mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Twisted/asyncio impedance | Timeouts, deadlocks | Mandatory AsyncioSelectorReactor; non-blocking pool checkout |
| Downloader slot starvation on escalate | Engine freeze under WAF storms | Re-schedule L2; never await pool inside L1 middleware (§5.5) |
| Challenge thundering herd | Wasted solves, IP challenge loops, cookie races | Per-session challenge mutex (§5.3.1) |
| Post-solve micro-herd | Fresh clearance burned by cadence/rate limits | Sibling stagger within fresh window (§5.3.3) |
| JS AST on reactor thread | Event-loop stall; cascading timeouts | Offload to thread/process pool (§10.3.1) |
| RFPDupeFilter drops L2 retry | Silent “success” with no bypass | TransportAwareDupeFilter + `dont_filter` on escalate (§5.6) |
| UA/profile mismatch | Instant Akamai/CF block | Profile-sourced personas only (§7.2) |
| L1↔L2 Chromium major drift | Clearance invalidated on handoff | Playwright major is TLS anchor (§5.3.2); fail closed if no catalog match |
| CAPTCHA solve vs checkout TTL | Mid-solve kills; re-schedule storms | Split queue vs execution timeouts (§5.2.1) |
| apisnoop large bodies | Worker OOM | `MAX_BODY_SIZE` truncation (§7.8.1) |
| Headless flags in Docker | Stealth failure / crash | Headed + Xvfb entrypoint (§7.5 / §10.9) |
| L1↔L2 clearance invalidation | Challenge storms, wasted residential bandwidth | Session Sync coherence asserts before de-escalation |
| DNS/WebRTC leak | OPSEC failure, ROE incident | Proxy DNS + WebRTC disabled; leak-check in doctor |
| HTTP/2 fingerprint drift | Silent Akamai/CF blocks despite good TLS | curl_cffi profile contract tests; catalog binding |
| L1 honeypot follows | Immediate bot flag | Defer unverified links to L2 validation queue |
| HAR/PNG on every page | Disk/I/O collapse on large scopes | Conditional capture defaults |
| Anti-bot vendors evolve weekly | Sudden success-rate drop | Progressive modes + unlocker fallback; canary alerts |
| Stealth plugins go stale | L2 detection | Abstract stealth backend; track Playwright/Chromium versions |
| Residential proxy cost | Budget overrun | Start L0/L1; escalate only on signals; cache clearance via Session Sync |
| Over-aggression | Accidental DoS / ROE breach | Hard rate ceilings; Autothrottle; engagement time bounds |
| PII in artifacts | Compliance incident | Redaction pipeline; field allowlists; encrypted pack for handoff |

---

## 17. Ethical & legal constraints (operator obligations)

Ariadne encodes technical controls, but operators remain responsible for:

1. Valid written authorization covering all target hosts and techniques used.  
2. Compliance with applicable law (e.g., CFAA interpretation, GDPR/CCPA for personal data).  
3. Minimizing collected personal data; retaining artifacts only as long as the engagement requires.  
4. Preferring official APIs or customer-provided data exports when they satisfy test objectives.  
5. Not representing traffic as a search-engine bot unless the ROE explicitly allows it.  
6. Understanding that `observe` / `ignore` robots modes increase sensitivity — ensure ROE covers this posture.  

The default posture is **scoped, OPSEC-safe, reversible recon** — not maximum-aggression scraping.

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
│   ├── settings.py         # AsyncioSelectorReactor mandated here
│   ├── items.py
│   ├── session/            # Session Synchronization Service + challenge mutex
│   ├── browser/            # Browser Pool + checkout manager
│   ├── dupefilters/        # TransportAwareDupeFilter
│   ├── stealth/            # profiles.yaml + chromium.py TLS anchor
│   ├── spidermiddlewares/
│   ├── downloadermiddlewares/
│   ├── downloadhandlers/   # curl_cffi (TLS+H2), playwright pool
│   ├── pipelines/
│   ├── extensions/
│   ├── proxies/            # generic proxy URL helpers (no vendor SDKs in MVP)
│   ├── challenges/
│   ├── spiders/
│   └── reporting/
├── engagements/            # example configs (no secrets)
├── tests/
└── docker/                 # Dockerfile + xvfb-run entrypoint (headed stealth)
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

v1.1 additionally incorporated internal red-team review on Twisted/asyncio impedance, L1↔L2 session handoff, DNS/WebRTC OPSEC, HTTP/2 frame fingerprints, L1 honeypot deferral, robots `observe` default, and conditional evidence I/O.

v1.2 incorporates Scrapy execution review: non-blocking escalation (downloader slot starvation), per-session challenge mutex (thundering herd), transport-aware DupeFilter, and profile-sourced persona generation.

v1.2.1 adds mandatory escalation priority, proxy-burn lifecycle, Playwright zombie teardown, and root Chromium process recycle.

v1.3.0 elevates Phase 2 physical realities to normative requirements: Playwright Chromium as L1↔L2 **TLS anchor**, **split queue/execution timeouts** for CAPTCHA pool safety, **`MAX_BODY_SIZE`** for apisnoop OOM prevention, and **headed+Xvfb** Docker stealth.

v1.4.0 adds Phase 3 traps: L3 **`locked_to_mode`** (no Franken-sessions), CAPTCHA **injection strategies**, **circuit breaker** on extraction drift, and **pubkey-file / age** pack encryption.

v1.4.1 adds last-mile traps: **post-solve sibling stagger** (micro-herd) and **JS AST reactor offload** for Phase 4.

---

## 20. Decisions (resolved)

| # | Question | Decision |
| --- | --- | --- |
| 1 | Proxy vendor adapters vs generic? | **Generic HTTP(S) proxy URLs only for MVP.** Operators encode provider geo/session in userinfo. No Bright Data/Oxylabs first-party SDKs until a clear need. |
| 2 | SeleniumBase UC in MVP? | **Playwright-only** through Phase 2. Dual automation stacks deferred to Phase 4 if required. |
| 3 | Evidence retention / encryption? | **Local ephemeral artifacts.** `ariadne pack --encrypt --pubkey <file>` — prefer **age**; never rely on host GPG keyrings in Docker/CI. |
| 4 | Dual attestation for `robots: ignore`? | **No.** Operators are already under assumed authorization; avoid administrative nagging in a tactical CLI. |
| 5 | Minimum Chromium for CI? | Pin to the Playwright-bundled Chromium version for the locked Playwright release in `pyproject.toml`; document in `ariadne doctor`. |
| 6 | Escalate by awaiting L2 in middleware? | **No.** Always re-schedule; free the downloader slot (§5.5). |
| 7 | Concurrent solves per session? | **Exactly one** via challenge mutex (§5.3.1). |
| 8 | How to avoid DupeFilter dropping L2? | **TransportAwareDupeFilter** + `dont_filter=True` on escalate (§5.6). |
| 9 | UA vs curl_cffi profile precedence? | **Profile is source of truth** for headers; when L2 on, **Playwright Chromium major** selects which profile (§5.3.2 / §7.2). |
| 10 | Escalation request priority? | **Mandatory high priority** (default 100) so L2 solves beat deep L1 queues within lease TTL. |
| 11 | Sticky proxy burned / IP change? | Drop clearance, rotate proxy, keep persona, full L2 re-escalate — never reuse IP-bound cookies. |
| 12 | Playwright on SIGTERM? | Close all browsers on `engine_stopped` / signal handlers before reactor shutdown. |
| 13 | Chromium process leaks? | Recycle root browser after MaxContextsServed; drain then kill. |
| 14 | L1↔L2 TLS fingerprint anchor? | **Playwright bundled Chromium major** is immutable; curl_cffi must match — never rotate majors under L2. |
| 15 | CAPTCHA vs pool checkout timeout? | **Split timeouts:** queue (acquire) vs execution (solve hold). Default 60s / 180s. |
| 16 | apisnoop large response bodies? | Enforce **`MAX_BODY_SIZE` (2 MiB default)**; truncate bodies, keep EndpointItem metadata. |
| 17 | Headed Playwright in Docker? | **Xvfb** via `xvfb-run` entrypoint; default `headless=false`. |
| 18 | L3 unlocker cookies to L1/L2? | **Forbidden.** Set `locked_to_mode=L3`; burn session to leave L3 (§5.4.1). |
| 19 | CAPTCHA after token fetch? | **InjectionStrategy** plugins: form / JS callback / click — target-specific (§7.7.1). |
| 20 | Extraction drift under load? | **Circuit breaker** drains and exits critical — no alert spam (§7.10.1). |
| 21 | GPG in Docker for pack? | **No ambient keyring.** Explicit `--pubkey` file; prefer age/pyrage. |
| 22 | Sibling wake after solve — probe vs full GET? | **Full L1 GET**, but **staggered** within `CLEARANCE_FRESH_WINDOW` (§5.3.3). No simultaneous burst. |
| 23 | Heavy JS route extraction where? | **Off reactor** via `asyncio.to_thread` / process pool (§10.3.1). |

### 20.1 Remaining open (non-blocking)

1. Optional Redis-backed Session Sync for multi-process Scrapy clusters (post-MVP) — mutex semantics must be distributed if so.  
2. Cadence for refreshing `profiles.yaml` when Playwright / `curl_cffi` release new Chromium builds.  
3. Which commercial unlocker vendors to ship first-class adapters for (generic HTTP unlocker URL template vs SDKs).  

v1.3.0 added Phase 2 physical traps: Playwright TLS anchor, split timeouts, MAX_BODY_SIZE, headed+Xvfb.

v1.4.0 adds Phase 3 operational traps: **L3 `locked_to_mode`**, **CAPTCHA injection strategies**, **circuit breaker**, and **pubkey-file / age encryption UX**.

v1.4.1 resolves post-solve **micro-herd stagger** (§5.3.3 / decision 22) and specifies **JS AST reactor offload** (§10.3.1 / decision 23) for Phase 4.

---

## 21. Next implementation step

**Phase 1–3 are shipped.** Operators may run engagements with L0–L3, Session Sync, circuit breaker, and encrypted packs.

**Phase 4 (optional):** implement `JsRouteHintExtractor` with mandatory offload (§10.3.1); multi-engine / AI extract only if required by a documented target class.
