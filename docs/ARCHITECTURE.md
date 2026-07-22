# Architecture

Operator-facing map of how Ariadne pieces fit together. Normative detail lives in [SPEC.md](../SPEC.md) v1.4.3.

---

## 1. Process model

```text
┌─────────────────────────────────────────────────────────────┐
│  ariadne crawl  (single OS process)                         │
│  Twisted AsyncioSelectorReactor  ←── mandatory              │
│                                                             │
│  SessionSyncService (in-process, thread-safe)               │
│  BrowserPool (optional Playwright, headed)                  │
│  Scrapy engine + downloader + spider middlewares            │
└─────────────────────────────────────────────────────────────┘
```

**Decision 28:** no multi-worker Scrapy Cluster / Redis Session Sync in MVP. Horizontal scale = multiple independent engagements (different hosts/scopes), not one shared mutex.

---

## 2. Transport ladder

| Mode | Implementation | Fingerprint | Notes |
| --- | --- | --- | --- |
| `L0_http` | Scrapy HTTP/1.1 fallback | Weak | Internal / low bar |
| `L1_impersonate` | `curl_cffi` AsyncSession | TLS JA3 + HTTP/2 via impersonate profile | Default |
| `L2_browser` | Playwright context from pool | Real bundled Chromium | TLS **anchor** for L1 profile selection |
| `L3_unlocker` | HTTP template → vendor unlocker | Vendor’s stack | `locked_to_mode`; isolated `l3_cookie_jar` |

### TLS anchor (L1↔L2)

Playwright’s Chromium **major** selects allowed `curl_cffi` profiles from `ariadne/stealth/profiles.yaml`. Mismatched majors invalidate clearance on handoff. Firefox profiles are L1-only when L2 is enabled.

### Escalation path (non-blocking)

```text
L1 response → ChallengeDetectMiddleware
    → try_begin_challenge(session_id)? 
         yes → return high-priority Request(transport=L2)  # frees slot
         no  → return Request(waiting_for_clearance=True)
L2 handler → pool.checkout → solve → set cookies → release_challenge(solved)
siblings → stagger if clearance fresh → L1 resume
```

Never await the browser pool inside L1 middleware.

---

## 3. Session Sync

Per `session_id` (default `host:{hostname}`):

| Field | Role |
| --- | --- |
| `persona` | Profile-derived UA, Sec-CH-UA, impersonate id |
| `cookie_jar` | L1/L2 clearance only |
| `l3_cookie_jar` | Unlocker cookies — never merged into L1/L2 |
| `locked_to_mode` | Forces transport (e.g. `L3_unlocker`) |
| `challenge_state` | idle → solving → solved \| failed |
| `clearance_solved_at` / `_wake_seq` | Post-solve sibling stagger |
| `clearance_exit_ip` | Optional active canary binding |
| `proxy_endpoint` | Sticky URL |

### Mutex

Exactly one L2 solve per session at a time (`try_begin_challenge`). Lease TTL prevents deadlock.

### Post-solve stagger (§5.3.3)

Within `ARIADNE_CLEARANCE_FRESH_WINDOW` (5s), waking siblings delay (jitter 0.5–5s or `base * index`) via `asyncio.sleep` so DataDome/CF cadence checks do not burn fresh clearance.

### Transparent IP (§5.3.4)

If L1 re-challenges within 60s of a solve → assume sticky exit IP rotated → `burn_sticky_proxy` (cap 3). Active canary (optional) must be OPSEC-isolated — see §5 below.

### Franken-session (§5.4.1)

L3 success → `lock_to_mode(L3)`. Leaving L3 requires `burn_session`, not cookie transplant.

---

## 4. Middleware pipeline

### Downloader (ascending order)

| Priority | Middleware | Role |
| --- | --- | --- |
| 40 | `CircuitBreakerMiddleware` | L3 trip → `IgnoreRequest` before wire |
| 50 | `ScopeMiddleware` | Allow/deny domains & regex; canary skip |
| 75 | `SessionSyncMiddleware` | Persona, cookies, lock, stagger |
| 100 | `PersonaHeadersMiddleware` | Header overlay (skipped for canary) |
| 350 | `ProxyMiddleware` | Attach proxy |
| 550 | `BackoffMiddleware` | 429 / Retry-After |
| 585 | `ChallengeDetectMiddleware` | Detect → re-schedule escalate; transparent IP |

### Spider

| Priority | Middleware | Role |
| --- | --- | --- |
| 100 | `RobotsHintMiddleware` | Fetch robots once per host |
| 200 | `HoneypotFilterMiddleware` | Defer unverified / robots Disallow to L2 |
| 900 | `CircuitBreakerMiddleware` | Empty extraction window → trip |

Same circuit-breaker **singleton** on the crawler serves both spider evaluation and downloader kill-switch.

### Extensions

- `AsyncioReactorGuard` — abort if wrong reactor  
- `SessionSyncExtension` — construct service; TLS-anchor filter  
- `BrowserPoolExtension` — start/stop pool; signal + atexit + orphan reap  
- `EngagementBanner` — log authorization metadata  
- `KillSwitchExtension` — file/env stop  

### Download handlers

HTTP(S) → `CurlCffiDownloadHandler` → L1 / L2 Playwright / L3 unlocker by `transport_mode`.

### DupeFilter

`TransportAwareDupeFilter` — fingerprint includes `transport_mode` (+ clearance epoch) so L2 escalate of a seen L1 URL is not dropped.

---

## 5. CAPTCHA & unlockers

### CAPTCHA (`ariadne.captcha`)

Token fetch is insufficient. Injection strategies:

- `inject_and_submit_form`  
- `inject_and_trigger_callback` (requires explicit `callback_name`)  
- `inject_and_click_element`  

Optional via request `meta["captcha"]` on L2 under `execution_timeout` (not checkout timeout).

### L3 unlocker (`ariadne.unlockers`)

`ARIADNE_UNLOCKER_URL` template (`{url}` or append). On success: lock mode, store cookies in `l3_cookie_jar` only.

---

## 6. Circuit breakers

| Kind | Window / ratio / min (defaults) | Close reason | Kill behavior |
| --- | --- | --- | --- |
| Standard | 50 / 0.50 / 20 | `extraction_drift` | Scheduler close; non-L3 may drain |
| L3 | 10 / 0.40 / 5 | `extraction_drift_l3` | **IgnoreRequest** all further L3 |

Graceful drain alone is a **financial leak** on billed unlockers — L3 uses the kill-switch.

---

## 7. Exit-IP canary OPSEC

`ariadne.proxy_canary.build_exit_ip_canary_request`:

- Same sticky **proxy port**  
- **No** `session_id`, target cookies, persona, Referer  
- Generic Accept / canary UA  
- `ariadne_exit_ip_canary` + `ariadne_skip_scope`  

Session Sync and Persona middlewares no-op for canary requests.

---

## 8. Browser pool timeouts

| Timeout | Default | Meaning |
| --- | --- | --- |
| `checkout_timeout` | 60s | Wait in queue for a free context |
| `execution_timeout` | 180s | Hold after acquire (CAPTCHA / navigation) |

Never apply checkout TTL to the entire solve.

---

## 9. Docker / teardown

```text
entrypoint.sh
  trap cleanup EXIT INT TERM
  xvfb-run … ariadne …
  cleanup → pkill -P $$ (+ chrome remote-debugging patterns)
```

Python `BrowserPoolExtension` still closes Playwright on `engine_stopped` / signals / atexit, then best-effort orphan reap. Python close alone is insufficient when IPC dies first.

---

## 10. Artifact model

| Item | Source |
| --- | --- |
| `PageItem` | map / extract / apisnoop |
| `EndpointItem` | apisnoop network XHR/fetch |
| `RobotsHintItem` | robots observe |
| `FormItem` | HTML forms |
| `AssetItem` | Static assets (`discovery.include_assets`) |
| `OutboundLinkItem` | Cross-host links (record-only, never fetched) |
| `FailedUrlItem` | Download / depth / HTTP gaps |
| `UrlCandidateItem` | Sitemap / JS / form discoveries |
| `DefenseEventItem` | challenges, L3 lock, transparent IP, etc. |

Pipelines: validate → dedupe → NDJSON export.  
Union inventory: `ariadne report DIR --sitemap` → `sitemap.jsonl` ([SITEMAP.md](./SITEMAP.md)).

---

## 11. Trap index (implemented)

| Trap | Spec | Mitigation |
| --- | --- | --- |
| Twisted/asyncio impedance | §5.1 | Mandatory AsyncioSelectorReactor |
| Downloader slot starvation | §5.5 | Re-schedule escalate |
| Thundering herd | §5.3.1 | Challenge mutex |
| Post-solve micro-herd | §5.3.3 | Sibling stagger |
| TLS major mismatch | §5.3.2 | Chromium anchor |
| Checkout vs CAPTCHA TTL | §5.2.1 | Split timeouts |
| Franken-session | §5.4.1 | `locked_to_mode` + L3 jar |
| CAPTCHA token-only | §7.7.1 | Injection strategies |
| Empty extract spam | §7.10.1 | Circuit breaker |
| L3 billing drain | §7.10.2 | IgnoreRequest kill-switch |
| GIL / to_thread | §10.3.1 | ProcessPool for heavy JS (Phase 4 extractor) |
| Transparent sticky IP | §5.3.4 | Passive burn + isolated canary |
| robots Disallow traps | §2.3.1 | defer / inventory_only |
| Chromium zombies | §10.5.1 | Entrypoint pkill |
| GPG in Docker | §6.5 | `--pubkey` / age |

---

## 12. Package layout

```text
ariadne/
  browser/          Playwright pool + network sniffer
  captcha/          Solvers + injection strategies
  challenges/       Challenge / proxy-burn heuristics
  downloadhandlers/ curl_cffi, Playwright download
  downloadermiddlewares/
  spidermiddlewares/
  extensions/
  session/          Session Sync service
  stealth/          profiles.yaml + Chromium major detect
  unlockers/        L3 adapter
  reporting/        pack + encrypt
  spiders/          map, extract, apisnoop
  proxy_canary.py   OPSEC-isolated exit-IP probe
docs/               This documentation set
SPEC.md             Normative specification
```
