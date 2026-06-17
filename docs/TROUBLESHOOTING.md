# Troubleshooting

Symptoms, likely causes, and fixes. Architecture background: [ARCHITECTURE.md](./ARCHITECTURE.md). Spec traps: [SPEC.md](../SPEC.md).

---

## Install & reactor

### `doctor` fails: wrong `TWISTED_REACTOR`

**Cause:** Scrapy not using `AsyncioSelectorReactor`.  
**Fix:** Install via `pip install -e .` so `ariadne.settings` is used; CLI sets `SCRAPY_SETTINGS_MODULE=ariadne.settings`. Do not override with a classic Twisted reactor.

### `curl_cffi` / profile errors

**Cause:** Missing dependency or empty catalog after TLS-anchor filter.  
**Fix:** `pip install -e ".[dev]"`; for L2 `pip install -e ".[browser]" && playwright install chromium`. If L2 on and no profile matches Chromium major, add a matching entry to `profiles.yaml` or upgrade Playwright/curl_cffi together.

---

## Clearance & challenges

### Clearance works in L2 then fails on L1

| Check | Action |
| --- | --- |
| Chromium major vs impersonate profile | `ariadne doctor` — majors must match |
| Sticky proxy rotated | Transparent IP: look for `transparent_ip_rotation` events; ensure proxy list has alternates |
| Franken-session | If traffic went through L3, do not expect L1 reuse — burn session or stay on L3 |
| Post-solve burst | Confirm stagger settings; cadence blocks look like “instant re-challenge” |

### Challenge storm / crawl stalls

**Cause:** Awaiting browser pool in middleware (must not), or low escalation priority buried under deep L1 queue.  
**Fix:** Ensure `escalation_priority` ≥ 100; pool checkout only in L2 handler; siblings use `waiting_for_clearance` re-schedule.

### Infinite escalate ↔ solve loop

**Cause:** Transparent sticky exit-IP rotation, or burned IP with reused clearance.  
**Fix:** Passive burn should rotate proxy; check `ARIADNE_TRANSPARENT_IP_MAX_BURNS` (default 3) — if capped, rotate provider sticky session IDs manually.

---

## L3 unlocker

### `L3 unlocker requested but ARIADNE_UNLOCKER_URL is unset`

Set env or setting to a template:

```bash
export ARIADNE_UNLOCKER_URL='https://api.vendor/?key=…&url='
# or with placeholder:
export ARIADNE_UNLOCKER_URL='https://api.vendor/?key=…&url={url}'
```

### High unlocker bill / hollow pages

**Cause:** Extractors broken under UI drift while L3 still returns 200.  
**Fix:** L3 circuit should trip with `extraction_drift_l3` and **IgnoreRequest** further L3. If trip did not fire, lower `ARIADNE_CIRCUIT_L3_*` thresholds. Fix selectors before re-enabling L3.

### Want to leave L3

Burn the session (`burn_session`) / use a new `session_id` — never copy `cf_clearance` from `l3_cookie_jar` into L1.

---

## Circuit breaker exits

| Reason | Meaning |
| --- | --- |
| `extraction_drift` | Empty extract ratio over std window |
| `extraction_drift_l3` | Empty extract ratio over L3 window (faster) |

**Fix:** Inspect NDJSON for empty `extraction`; update spider selectors; run a small canary before full crawl.

Stats keys: `ariadne/circuit_breaker_trip`, `ariadne/circuit_breaker_l3`, `ariadne/circuit_breaker_l3_dropped`.

---

## Playwright / Docker

### Zombie Chromium after Ctrl-C

**Cause:** IPC severed before `browser.close()`.  
**Fix:** Use the Docker entrypoint (or equivalent trap + `pkill -P`). Bare `python -m scrapy` without reaper is riskier. Extension atexit also attempts orphan reap.

### Headless detected / soft-fail Turnstile

**Cause:** `--headless=new` tells.  
**Fix:** Keep `headless: false` and run under Xvfb (`ARIADNE_USE_XVFB=1`).

### Pool checkout timeouts during CAPTCHA

**Cause:** Confusing checkout vs execution timeout.  
**Fix:** Raise `execution_timeout_seconds` (e.g. 180–300); leave checkout at ~60 for queue fairness.

### apisnoop OOM / huge responses

Bodies truncate at `ARIADNE_MAX_BODY_SIZE` (2 MiB). Endpoint metadata remains; full body is not stored.

---

## robots / honeypots

### IP burned after crawling Disallows

**Cause:** Aggressive `follow` policy or treating Disallows as organic.  
**Fix:** Set `ARIADNE_ROBOTS_HINT_POLICY=inventory_only` or keep `defer` with high delay; confirm ROE before `follow`.

### Links never fetched from L1

**Cause:** `honeypot_suspect` + `defer` escalates to L2 validation.  
**Fix:** Expected; enable browser pool or allow L2 stub in tests. Set `l1_unverified: follow` only when accepting risk.

---

## Pack / encryption

### `pack failed: --encrypt requires --pubkey`

Pass `--pubkey /path/to/recipient.age` (or `.asc`).

### `age CLI not found`

Install [age](https://age-encryption.org) on PATH, or use a GPG **public key file** (temporary GNUPGHOME import — still no host keyring).

### pinentry / `~/.gnupg` errors

Ariadne must not use ambient GPG. Ensure you are not wrapping with external GPG that reads the host keyring.

---

## Scope

### `IgnoreRequest: host … not in allow_domains`

Expand `scope.allow_domains` / regex, or fix redirects leaving scope. Exit-IP canary uses `ariadne_skip_scope` intentionally.

---

## Tests

```bash
pytest -q
```

If browser tests fail locally without Chromium, use `.[dev]` unit suite; browser-dependent paths are gated by `ARIADNE_BROWSER_POOL_ENABLED`.

---

## Logging signals worth grepping

| Log / event | Meaning |
| --- | --- |
| `Escalating … → L2` | Challenge mutex won |
| `Staggering post-solve wake` | Micro-herd protection |
| `Transparent IP rotation` | Sticky exit IP assumed changed |
| `L3 lock engaged` | Franken-session guard on |
| `L3 circuit open — dropping` | Financial kill-switch |
| `Circuit breaker TRIP` | Drift exit |
| `BrowserPoolExtension: pool stopped` | Teardown ran |
