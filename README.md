# Ariadne

Authorized-scope security testing web crawler for red team and penetration-testing engagements.

Built on **Scrapy** (`AsyncioSelectorReactor`), **curl_cffi** (L1 TLS + HTTP/2 impersonation), and **Playwright** (L2 headed stealth pool). Designed as a **single-node CLI** — one process per engagement, in-process Session Sync (no Redis cluster required for MVP).

| Document | Purpose |
| --- | --- |
| **[SPEC.md](./SPEC.md)** (v1.4.3) | Normative product & technical specification — architecture, traps, acceptance criteria |
| **[docs/README.md](./docs/README.md)** | Documentation index |
| **[docs/OPERATOR.md](./docs/OPERATOR.md)** | Operator runbook — install, engage, crawl, pack, Docker |
| **[docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)** | Transport ladder, Session Sync, middleware pipeline |
| **[docs/CONFIGURATION.md](./docs/CONFIGURATION.md)** | Engagement YAML + `ARIADNE_*` settings reference |
| **[docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)** | Clearance drops, zombies, circuit trips, common failures |

---

## What Ariadne is (and is not)

### Capable of

- **Authorized-scope recon crawling** — map links, forms, robots hints, and simple extractions within engagement allowlists.
- **Progressive anti-bot escalation** — L0 HTTP → L1 TLS/HTTP2 impersonation (`curl_cffi`) → L2 headed Playwright → optional L3 commercial unlocker, with coherent Session Sync (persona, cookies, sticky proxy).
- **WAF / challenge handling (best-effort)** — detect common challenge patterns, serialize one solve per session, stagger sibling wake-ups, and inject CAPTCHA tokens via target-specific strategies (form / callback / click).
- **Client-side API inventory (`apisnoop`)** — capture XHR/fetch metadata with bounded body size; produce NDJSON recon artifacts for reports.
- **OPSEC-aware defaults** — WebRTC disabled in the browser pool, proxy-oriented DNS guidance, robots Disallow treated as honeypot-class (not organic crawl fuel), L3 cookies locked so they never poison L1/L2.
- **Engagement safety rails** — scope enforcement, rate/backoff controls, extraction circuit breakers (including L3 financial kill-switch), kill-switch / clean teardown, encrypted evidence packs via explicit `--pubkey`.

### Not capable of (non-goals)

- **Guaranteed bypass** of every CAPTCHA, bot vendor, or hardened enterprise WAF — escalation improves odds; it does not promise 100% success.
- **Exploitation** — no exploit payloads, PoCs, or vulnerability weaponization; output is recon evidence, not attack automation.
- **Replacing your ROE / authorization** — YAML scope is an enforcement aid, not legal cover.
- **Commodity scraping SaaS** — not a marketplace price scraper, SEO crawler, or multi-tenant cloud service.
- **Distributed Scrapy Cluster / Redis Session Sync** — single-node CLI only for MVP; no shared multi-process challenge mutex.
- **Vendor-complete proxy/unlocker SDKs** — generic HTTP(S) proxy URLs and unlocker URL templates; not first-party adapters for every provider.
- **Dual browser stacks** — Playwright-only for MVP (no Selenium / undetected-chromedriver as a primary path).
- **Autonomous AI browsing as the primary crawler** — not an LLM agent that “uses the site” end-to-end (optional Phase 4 at most).
- **Magic CAPTCHA submission** — token APIs alone are not enough; site-specific injection config is required for many Turnstile/reCAPTCHA flows.
- **Safe L3 → L1 cookie reuse** — unlocker clearance is vendor-bound; Ariadne will not Franken-session those cookies onto residential L1/L2.

If a capability is not listed above, assume it is out of scope until the [SPEC](./SPEC.md) says otherwise.

---

## Authorization

**Only crawl targets you are authorized to test.** Engagement YAML encodes client, operator, allowlists, and (optionally) `authorized_until`. Ariadne enforces scope at the downloader; it does not replace a Rules of Engagement document.

Default `respect_robots: observe` inventories `Disallow` paths as recon hints and fetches them under a **defer / rate-limited** policy — not as organic crawl fuel. Use `obey` when the ROE requires it.

---

## Status

| Phase | Scope | State |
| --- | --- | --- |
| 1 | Scrapy core, Session Sync, challenge mutex, L1 curl_cffi, TransportAwareDupeFilter | Shipped |
| 2 | Playwright pool, Chromium TLS anchor, split timeouts, apisnoop `MAX_BODY_SIZE`, Xvfb Docker | Shipped |
| 3 | L3 unlocker + `locked_to_mode`, CAPTCHA injection strategies, circuit breaker, `pack --encrypt --pubkey` | Shipped |
| 3.1 / 4 edges | Post-solve stagger, L3 `IgnoreRequest` kill-switch, transparent IP, robots defer, OS Chromium reap, exit-IP canary isolation | Spec locked + implemented |
| 4 optional | `JsRouteHintExtractor` (ProcessPool), scheduled active IP canary, multi-engine/AI | Not required for MVP |

**Deployment model (Decision 28):** single-node CLI. Distributed Session Sync is explicitly out of MVP.

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ariadne doctor
ariadne init engagement.yaml          # or copy engagements/example.yaml
ariadne validate engagement.yaml
ariadne crawl -c engagement.yaml
```

### With Playwright (L2 / apisnoop)

```bash
pip install -e ".[browser]"
playwright install chromium
ariadne doctor --leak-check
ariadne crawl -c engagement.yaml --spider apisnoop
```

### Evidence pack

```bash
ariadne report ./artifacts/ENGAGEMENT-ID
ariadne pack ./artifacts/ENGAGEMENT-ID
ariadne pack ./artifacts/ENGAGEMENT-ID --encrypt --pubkey recipient.age
```

Encryption requires an **explicit recipient public key file** (`--pubkey`). Prefer **age**. No ambient `~/.gnupg` / pinentry in Docker.

### Docker (headed stealth)

```bash
docker build -f docker/Dockerfile -t ariadne .
docker run --rm ariadne ariadne doctor --leak-check
docker run --rm \
  -v "$PWD/engagements:/app/engagements" \
  -v "$PWD/artifacts:/app/artifacts" \
  ariadne ariadne crawl -c engagements/example.yaml --spider apisnoop
```

The entrypoint wraps the process under **Xvfb**, traps EXIT/INT/TERM, and reaps Chromium children (`pkill`) so Playwright zombies do not survive chaotic asyncio shutdown.

---

## CLI

| Command | Purpose |
| --- | --- |
| `ariadne version` | Package version |
| `ariadne doctor` | Reactor, profiles, curl_cffi, Playwright Chromium TLS anchor |
| `ariadne doctor --leak-check` | WebRTC launch-arg / DNS-via-proxy guidance |
| `ariadne init [path]` | Starter engagement YAML |
| `ariadne validate PATH` | Validate engagement schema |
| `ariadne crawl -c PATH [--spider map\|extract\|apisnoop]` | Run crawl |
| `ariadne report DIR` | Markdown summary from NDJSON artifacts |
| `ariadne pack DIR [--encrypt --pubkey FILE]` | Zip (+ encrypt) evidence |

---

## Transport ladder (summary)

```text
L0_http          Scrapy HTTP          low protection / internal
L1_impersonate   curl_cffi TLS+H2     default external recon
L2_browser       Playwright pool      JS / WAF solve (headed + Xvfb)
L3_unlocker      commercial unlocker  last resort; session locked_to_mode=L3
```

Escalation is **non-blocking**: challenge detection re-schedules a high-priority request and frees the downloader slot. One WAF solve per `session_id` (mutex). Sibling wake-ups after solve are **staggered**. L3 clearance never de-escalates into L1/L2 jars.

See [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md).

---

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

---

## License

MIT — see `pyproject.toml`.
