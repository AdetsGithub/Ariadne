# Operator runbook

Authorized-scope crawl lifecycle for Ariadne (single-node CLI).

---

## 1. Prerequisites

| Requirement | Notes |
| --- | --- |
| Python 3.11+ | Verified with Scrapy asyncio reactor |
| Authorization / ROE | Written scope; engagement YAML is not a substitute |
| Residential proxies (recommended) | Sticky session URLs for L1↔L2 clearance coherence |
| Optional: Playwright Chromium | `pip install -e ".[browser]" && playwright install chromium` |
| Optional: `age` CLI | For `ariadne pack --encrypt --pubkey …` |

---

## 2. Install

```bash
git clone <repo> && cd Ariadne
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                 # L1 + tests
# For L2 / apisnoop:
pip install -e ".[browser]"
playwright install chromium
```

Health check:

```bash
ariadne doctor
ariadne doctor --leak-check   # WebRTC disabled in launch args; DNS-via-proxy reminder
```

`doctor` must report `TWISTED_REACTOR: …AsyncioSelectorReactor OK`. If not, do not crawl.

---

## 3. Engagement YAML

```bash
ariadne init engagement.yaml
# edit: engagement.*, scope.*, crawl.start_urls, proxies.urls
ariadne validate engagement.yaml
```

Minimal checklist:

1. **`engagement.id` / `client` / `operator`** — appear in artifacts and reports.  
2. **`scope.allow_domains` + `allow_url_regex`** — hard allowlist.  
3. **`scope.deny_url_regex`** — e.g. logout, destructive actions.  
4. **`crawl.start_urls`** — in-scope HTTPS seeds.  
5. **`crawl.proxies.urls`** — sticky residential endpoints when facing WAFs.  
6. **`respect_robots`** — default `observe` (see §6).  

Full field reference: [CONFIGURATION.md](./CONFIGURATION.md). Example: [`engagements/example.yaml`](../engagements/example.yaml).

---

## 4. Choose a spider / mode

| Mode / `--spider` | Purpose |
| --- | --- |
| `map` (default) | Link discovery, forms, robots hints → `PageItem` / `FormItem` / `RobotsHintItem` |
| `extract` | Map + simple heading / JSON-LD extraction |
| `apisnoop` | Enables browser pool + network capture; XHR/fetch → `EndpointItem` (bodies truncated at `MAX_BODY_SIZE`) |

```bash
ariadne crawl -c engagement.yaml
ariadne crawl -c engagement.yaml --spider extract
ariadne crawl -c engagement.yaml --spider apisnoop
```

Artifacts land under `{output.dir}/{engagement.id}/` (e.g. `./artifacts/EXAMPLE-001/`).

---

## 5. Transport & escalation (operator view)

Start at **L1** (`curl_cffi`) unless the target needs a browser immediately.

| Mode | When |
| --- | --- |
| L0 | Internal / low protection (rare) |
| L1 | Default recon |
| L2 | JS challenges, honeypot validation, apisnoop |
| L3 | Commercial unlocker after L2 exhaustion — **session stays on L3** until burned |

Operators should set:

```yaml
crawl:
  transport:
    initial_mode: L1_impersonate
    escalate_to: [L2_browser]          # or [L2_browser, L3_unlocker]
```

L3 requires `ARIADNE_UNLOCKER_URL` (env or settings) — URL template that embeds/appends the target URL. After any L3 success, Ariadne sets `locked_to_mode=L3_unlocker` and **never** merges vendor cookies into the L1/L2 jar.

---

## 6. robots.txt policy

| Mode | Behavior |
| --- | --- |
| `observe` (default) | Parse robots; emit `RobotsHintItem`; Disallow fetches use **`ARIADNE_ROBOTS_HINT_POLICY`** |
| `obey` | Skip Disallow paths |
| `ignore` | Do not fetch robots.txt |

Disallow fetch policies (`ARIADNE_ROBOTS_HINT_POLICY`):

| Policy | Behavior |
| --- | --- |
| `defer` (default) | Schedule with honeypot-class defer + low priority + delay (safer) |
| `inventory_only` | Record hints only — **no** Disallow fetches |
| `follow` | Aggressive Disallow probing (ROE must allow) |

WAFs seed trap Disallows (e.g. `/wp-admin/db-backup.sql.gz`). Prefer `defer` or `inventory_only`.

---

## 7. Proxies & OPSEC

- Prefer **sticky residential** URLs; clearance cookies are IP-bound.  
- On sticky burn / transparent exit-IP rotation, Ariadne drops clearance, rotates endpoint, keeps persona, re-escalates.  
- WebRTC is disabled in BrowserPool launch args; use SOCKS5h / provider remote-DNS so host DNS does not leak.  
- Active exit-IP canary (optional): **bare L1** through the sticky port only — never target cookies/persona/Referer. See SPEC §5.3.4.1.

Kill switch: create file `.ariadne.kill` in the CWD (or configured watcher path) / send SIGTERM — engine drains; Docker entrypoint reaps Chromium.

---

## 8. Circuit breakers

| Trip | Meaning | Operator action |
| --- | --- | --- |
| `extraction_drift` | Sustained empty extractions (L0–L2) | Fix selectors / canaries; re-run |
| `extraction_drift_l3` | Faster trip on paid unlocker hollow pages | Fix extract rules **before** re-enabling L3 |

On L3 trip, further L3 requests are **`IgnoreRequest`**’d — not allowed to drain and bill.

---

## 9. Artifacts & handoff

Typical files under `artifacts/{id}/`:

| File | Content |
| --- | --- |
| `PageItem.ndjson` | Pages crawled |
| `EndpointItem.ndjson` | APIs (apisnoop) |
| `RobotsHintItem.ndjson` | Disallow/Allow inventory |
| `FormItem.ndjson` | Forms |
| `engagement.json` | Engagement snapshot |
| `screenshots/` | Conditional (challenge/error) |
| `summary.md` | From `ariadne report` |

```bash
ariadne report ./artifacts/EXAMPLE-001
ariadne pack ./artifacts/EXAMPLE-001
ariadne pack ./artifacts/EXAMPLE-001 --encrypt --pubkey ./keys/client.age
```

**Encrypt rules:** pass `--pubkey` to a recipient **file**. Prefer `age1…` keys. Optional OpenPGP `.asc` uses a **temporary** `GNUPGHOME` — never host keyring / pinentry.

---

## 10. Docker

```bash
docker build -f docker/Dockerfile -t ariadne .
docker run --rm \
  -e ARIADNE_UNLOCKER_URL='https://api.example/unlock?url=' \
  -v "$PWD/engagements:/app/engagements" \
  -v "$PWD/artifacts:/app/artifacts" \
  -v "$PWD/keys:/keys:ro" \
  ariadne ariadne crawl -c engagements/prod.yaml --spider extract
```

Entrypoint:

1. Optional `xvfb-run` for headed Playwright.  
2. `trap` EXIT/INT/TERM → `pkill -P $$` Chromium reap.  
3. Does **not** bare-`exec` without a reaper.

---

## 11. Recommended engagement sequence

1. `doctor` (+ `--leak-check` if L2).  
2. Narrow `map` on one host with low concurrency.  
3. Inspect NDJSON + challenge stats; tune proxies / profiles.  
4. `extract` or `apisnoop` once L1/L2 clearance is stable.  
5. Enable L3 only with unlocker budget + extract rules already validated.  
6. `report` → `pack --encrypt` → deliver.

---

## 12. What Ariadne will not do

- Exploit or weaponize findings.  
- Bypass authorization / crawl out of `allow_domains`.  
- De-escalate L3 vendor cookies onto L1/L2 (Franken-session).  
- Blindly fire all robots Disallows at organic priority.  
- Rely on host GPG keyrings inside containers.
