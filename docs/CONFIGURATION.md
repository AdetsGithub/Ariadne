# Configuration reference

Engagement YAML is the primary operator interface. Scrapy/`ARIADNE_*` settings are applied from YAML at crawl time and can be overridden via environment for secrets and unlockers.

Normative behavior: [SPEC.md](../SPEC.md). Schema source: `ariadne/engagement.py`.

---

## 1. Engagement YAML

### Top-level

```yaml
engagement: { … }
scope: { … }
crawl: { … }
output: { … }          # optional; defaults apply
```

### `engagement`

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `id` | string | yes | Artifact directory name / report id |
| `client` | string | yes | Client name |
| `operator` | string | yes | Operator email / handle |
| `authorized_until` | ISO datetime | no | Informational expiry |

### `scope`

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `allow_domains` | list[str] | `[]` | Host allowlist |
| `allow_url_regex` | list[str] | `[]` | URL allow patterns (all must allow if set) |
| `deny_url_regex` | list[str] | `[]` | Hard deny |
| `max_depth` | int \| null | `5` | Link depth from seeds; `null` / `-1` / `unlimited` = no cap |
| `respect_robots` | `observe` \| `obey` \| `ignore` | `observe` | Robots policy |

### `crawl`
| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `mode` | `map` \| `extract` \| `apisnoop` \| … | `map` | Default spider when `--spider` omitted |
| `start_urls` | list[str] | required | Seeds |
| `transport` | object | see below | L0–L3 ladder |
| `concurrency` | object | see below | Rate / parallelism |
| `session` | object | see below | Mutex / escalate priority |
| `browser` | object | see below | Playwright pool |
| `honeypot` | object | `l1_unverified: defer` | Unverified link policy |
| `proxies` | object | see below | Sticky proxy list |
| `discovery` | object | see below | Comprehensive sitemap inventory knobs |

#### `crawl.discovery`

Best-effort URL inventory beyond HTML link-follows. Cross-host links are **never fetched**.
Full semantics: [SITEMAP.md](./SITEMAP.md).

| Field | Default | Description |
| --- | --- | --- |
| `sitemaps` | `true` | Parse `/sitemap.xml` and robots `Sitemap:` → depth-0 seeds |
| `include_assets` | `false` | Emit `AssetItem` for images/css/js/pdf/… |
| `asset_method` | `head` | `head` \| `get` \| `none` (URL-only) |
| `outbound_links` | `true` | Record off-host `<a href>` as `OutboundLinkItem` |
| `record_failures` | `true` | `FailedUrlItem` on download errors / max_depth skips |
| `record_http_errors` | `true` | Keep 4xx/5xx as `PageItem` via `handle_httpstatus_list` |
| `js_route_hints` | `false` | Heuristic path strings from inline scripts |
| `form_action_seeds` | `true` | Schedule in-scope GET form actions at depth 0 |

#### `crawl.transport`

| Field | Default | Description |
| --- | --- | --- |
| `initial_mode` | `L1_impersonate` | `L0_http` \| `L1_impersonate` \| `L2_browser` \| `L3_unlocker` |
| `escalate_to` | `[L2_browser]` | Escalation chain (first entry used by ChallengeDetect) |
| `impersonate_profiles` | catalog | Restrict curl_cffi profiles; filtered by Chromium major when L2 on |

#### `crawl.concurrency`

| Field | Default | Description |
| --- | --- | --- |
| `max_concurrent_requests` | `8` | → `CONCURRENT_REQUESTS` |
| `download_delay_mean` | `3.5` | → `DOWNLOAD_DELAY` |
| `download_delay_std` | `1.2` | Reserved for jitter helpers |

#### `crawl.session`

| Field | Default | Description |
| --- | --- | --- |
| `challenge_lease_ttl_seconds` | `120` | Mutex lease |
| `clearance_wait_delay_mean` | `2.0` | Sibling wait delay while solving |
| `escalation_priority` | `100` | High-priority re-schedule (mandatory) |

#### `crawl.browser`

| Field | Default | Description |
| --- | --- | --- |
| `headless` | `false` | Prefer headed + Xvfb |
| `pool_size` | `4` | Concurrent contexts |
| `checkout_timeout_seconds` | `60` | Queue wait |
| `execution_timeout_seconds` | `180` | Hold after checkout |
| `max_contexts_served` | `5000` | Recycle root browser after N |
| `disable_webrtc` | `true` | OPSEC |
| `proxy_dns` | `true` | Prefer DNS via proxy |
| `capture_network` | `false` | Force network sniffer |
| `humanize` | `true` | Light mouse/scroll |
| `stealth` | `true` | Reserved / documented intent |

Browser pool auto-enables for `apisnoop`, `auth`, `initial_mode` L2*, or `capture_network: true`.

#### `crawl.proxies`

| Field | Default | Description |
| --- | --- | --- |
| `class` | `residential` | Informational (`datacenter` \| `residential` \| `mobile`) |
| `sticky_ttl_seconds` | `600` | Informational sticky TTL |
| `urls` | `[]` | Proxy URL list (sticky session encoded in URL) |

#### `crawl.honeypot`

| Field | Default | Description |
| --- | --- | --- |
| `l1_unverified` | `defer` | `defer` → L2 validate; `follow` → risk; `risk_score` reserved |

### `output`

| Field | Default | Description |
| --- | --- | --- |
| `dir` | `./artifacts` | Base dir; final path `{dir}/{engagement.id}` |
| `formats` | `[ndjson, markdown_summary]` | Exporters |
| `redact_pii` | `true` | Pipeline flag |
| `capture.screenshots` | `on_challenge_or_error` | `never` \| `on_challenge_or_error` \| `always` |
| `capture.har` | `on_apisnoop_or_challenge` | Conditional HAR policy |

### Complete example

See [`engagements/example.yaml`](../engagements/example.yaml).

---

## 2. Environment variables

| Variable | Purpose |
| --- | --- |
| `ARIADNE_UNLOCKER_URL` | L3 unlocker template (`…&url=` or `{url}`) |
| `SCRAPY_SETTINGS_MODULE` | Defaults to `ariadne.settings` via CLI |
| `ARIADNE_USE_XVFB` | Docker entrypoint: `1` (default) enables xvfb-run |
| `ARIADNE_BROWSER_HEADLESS` | Docker image default `false` |
| Captcha provider keys | Provider-specific (when real adapters land); MVP uses `stub` |

Secrets (proxy passwords, unlocker keys) belong in env / secret mounts — never commit them.

---

## 3. `ARIADNE_*` Scrapy settings

Defaults from `ariadne/settings.py`. Engagement crawl maps the most common ones; the rest are tunables for advanced operators.

### Core / transport

| Setting | Default | Description |
| --- | --- | --- |
| `ARIADNE_INITIAL_TRANSPORT` | `L1_impersonate` | Starting mode |
| `ARIADNE_ESCALATION_PRIORITY` | `100` | Escalate / wait priority |
| `ARIADNE_CHALLENGE_LEASE_TTL` | `120` | Mutex lease seconds |
| `ARIADNE_CLEARANCE_WAIT_DELAY` | `2.0` | Waiter delay |
| `ARIADNE_IMPERSONATE_PROFILES` | catalog | Profile allowlist |
| `ARIADNE_PROXY_URL` / `ARIADNE_PROXY_LIST` | unset | Proxies |
| `ARIADNE_ENGAGEMENT` | unset | Injected dict from YAML |
| `ARIADNE_OUTPUT_DIR` | `artifacts` | Output root |

### Post-solve stagger

| Setting | Default | Description |
| --- | --- | --- |
| `ARIADNE_CLEARANCE_FRESH_WINDOW` | `5.0` | Seconds clearance is “hot” |
| `ARIADNE_SIBLING_STAGGER_BASE` | `0.5` | Base delay / jitter min |
| `ARIADNE_SIBLING_STAGGER_MAX` | `5.0` | Cap / jitter max |
| `ARIADNE_SIBLING_STAGGER_JITTER` | `True` | Uniform jitter vs `base * index` |

### Browser

| Setting | Default | Description |
| --- | --- | --- |
| `ARIADNE_BROWSER_POOL_ENABLED` | `False` | On for apisnoop / L2 initial |
| `ARIADNE_BROWSER_POOL_SIZE` | `4` | Contexts |
| `ARIADNE_BROWSER_CHECKOUT_TIMEOUT` | `60` | Queue |
| `ARIADNE_BROWSER_EXECUTION_TIMEOUT` | `180` | Hold |
| `ARIADNE_BROWSER_MAX_CONTEXTS_SERVED` | `5000` | Process recycle |
| `ARIADNE_BROWSER_HEADLESS` | `False` | Prefer headed |
| `ARIADNE_BROWSER_HUMANIZE` | `True` | Light interaction |
| `ARIADNE_CAPTURE_NETWORK` | `False` | XHR sniffer |
| `ARIADNE_MAX_BODY_SIZE` | `2097152` | 2 MiB apisnoop body cap |
| `ARIADNE_SCREENSHOT_MODE` | `on_challenge_or_error` | Screenshot policy |

### L3 / CAPTCHA

| Setting | Default | Description |
| --- | --- | --- |
| `ARIADNE_UNLOCKER_URL` | `None` | Unlocker template |
| `ARIADNE_CAPTCHA_PROVIDER` | `None` | `null` \| `stub` \| future providers |
| `ARIADNE_CAPTCHA` | unset | Optional dict for site_key + injection |

### Circuit breakers

| Setting | Default | Description |
| --- | --- | --- |
| `ARIADNE_CIRCUIT_WINDOW` | `50` | Std window |
| `ARIADNE_CIRCUIT_EMPTY_RATIO` | `0.50` | Std threshold |
| `ARIADNE_CIRCUIT_MIN_SAMPLES` | `20` | Std min |
| `ARIADNE_CIRCUIT_L3_WINDOW` | `10` | L3 window |
| `ARIADNE_CIRCUIT_L3_EMPTY_RATIO` | `0.40` | L3 threshold |
| `ARIADNE_CIRCUIT_L3_MIN_SAMPLES` | `5` | L3 min |

### Transparent IP / canary

| Setting | Default | Description |
| --- | --- | --- |
| `ARIADNE_TRANSPARENT_IP_WINDOW` | `60.0` | Seconds after solve for passive detect |
| `ARIADNE_TRANSPARENT_IP_MAX_BURNS` | `3` | Cap burns per session |
| `ARIADNE_EXIT_IP_CANARY` | `False` | Enable active canary scheduler (optional Phase 4) |

### robots / honeypot

| Setting | Default | Description |
| --- | --- | --- |
| `ARIADNE_RESPECT_ROBOTS` | `observe` | observe \| obey \| ignore |
| `ARIADNE_ROBOTS_HINT_POLICY` | `defer` | inventory_only \| defer \| follow |
| `ARIADNE_ROBOTS_HINT_DELAY` | `5.0` | Delay for Disallow fetches |
| `ARIADNE_HONEYPOT_L1_UNVERIFIED` | `defer` | defer \| risk_score \| follow |

### Future JS parse (Phase 4 extractor)

Documented in SPEC §10.3.1 (not yet wired as settings constants in MVP code):

| Intended setting | Intent |
| --- | --- |
| `ARIADNE_JS_PARSE_THREAD_MAX_BYTES` | Below this, thread/`to_thread` may be OK |
| `ARIADNE_JS_PARSE_MAX_BYTES` | Hard cap / skip |

Heavy AST → **`ProcessPoolExecutor` only** above the trivial threshold.

---

## 4. CAPTCHA request meta (L2)

```python
request.meta["captcha"] = {
    "site_key": "…",
    "challenge_type": "turnstile",  # or recaptcha / hcaptcha
    "provider": "stub",
    "injection": {
        "kind": "callback",           # form | callback | click
        "callback_name": "window.onCaptchaSuccess",
        "token_field_selector": 'textarea[name="cf-turnstile-response"]',
        "form_selector": "form",
        "click_selector": "#submit",
    },
}
```

`callback` kind **requires** `callback_name` — Ariadne will not guess `___grecaptcha_cfg` paths.

---

## 5. Exit-IP canary helper

```python
from ariadne.proxy_canary import build_exit_ip_canary_request, parse_exit_ip_body

req = build_exit_ip_canary_request(
    echo_url="https://operator-controlled-echo.example/ip",
    sticky_proxy=session.proxy_endpoint,
    callback=parse_canary_response,
)
```

Echo URL should be **operator-controlled** when possible (SPEC open question: no hard-coded third-party default).

---

## 6. Profiles catalog

`ariadne/stealth/profiles.yaml` maps profile ids → `impersonate`, `chromium_major`, UA, Client Hints, `l2_compatible`.

When L2 is enabled, Session Sync keeps only profiles matching Playwright’s bundled Chromium major.
