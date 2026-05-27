"""Scrapy settings for Ariadne — AsyncioSelectorReactor is mandatory."""

BOT_NAME = "ariadne"

SPIDER_MODULES = ["ariadne.spiders"]
NEWSPIDER_MODULE = "ariadne.spiders"

# --- Mandatory asyncio reactor (SPEC §5.1) ---
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

ROBOTSTXT_OBEY = False  # robots handled by Ariadne observe/obey/ignore policy

CONCURRENT_REQUESTS = 8
DOWNLOAD_DELAY = 0
COOKIES_ENABLED = True
TELNETCONSOLE_ENABLED = False
LOG_LEVEL = "INFO"

DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DOWNLOADER_MIDDLEWARES = {
    "ariadne.downloadermiddlewares.circuit_breaker.CircuitBreakerMiddleware": 40,
    "ariadne.downloadermiddlewares.scope.ScopeMiddleware": 50,
    "ariadne.downloadermiddlewares.session_sync.SessionSyncMiddleware": 75,
    "ariadne.downloadermiddlewares.persona.PersonaHeadersMiddleware": 100,
    "ariadne.downloadermiddlewares.proxy.ProxyMiddleware": 350,
    "ariadne.downloadermiddlewares.backoff.BackoffMiddleware": 550,
    "ariadne.downloadermiddlewares.challenge.ChallengeDetectMiddleware": 585,
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": None,
}

SPIDER_MIDDLEWARES = {
    "ariadne.spidermiddlewares.robots_hints.RobotsHintMiddleware": 100,
    "ariadne.spidermiddlewares.honeypot.HoneypotFilterMiddleware": 200,
    "ariadne.downloadermiddlewares.circuit_breaker.CircuitBreakerMiddleware": 900,
}

ITEM_PIPELINES = {
    "ariadne.pipelines.validate.ValidatePipeline": 100,
    "ariadne.pipelines.dedupe.DedupePipeline": 200,
    "ariadne.pipelines.ndjson.NdjsonExportPipeline": 900,
}

EXTENSIONS = {
    "ariadne.extensions.reactor_guard.AsyncioReactorGuard": 0,
    "ariadne.extensions.session_sync_ext.SessionSyncExtension": 100,
    "ariadne.extensions.browser_pool_ext.BrowserPoolExtension": 150,
    "ariadne.extensions.engagement.EngagementBanner": 200,
    "ariadne.extensions.kill_switch.KillSwitchExtension": 300,
}

DUPEFILTER_CLASS = "ariadne.dupefilters.TransportAwareDupeFilter"

DOWNLOAD_HANDLERS = {
    "http": "ariadne.downloadhandlers.curl_cffi_handler.CurlCffiDownloadHandler",
    "https": "ariadne.downloadhandlers.curl_cffi_handler.CurlCffiDownloadHandler",
}

# Ariadne-specific
ARIADNE_ESCALATION_PRIORITY = 100
ARIADNE_CHALLENGE_LEASE_TTL = 120
ARIADNE_CLEARANCE_WAIT_DELAY = 2.0
# Post-solve micro-herd: stagger sibling wake-ups while clearance is fresh
ARIADNE_CLEARANCE_FRESH_WINDOW = 5.0
ARIADNE_SIBLING_STAGGER_BASE = 0.5
ARIADNE_SIBLING_STAGGER_MAX = 5.0
ARIADNE_SIBLING_STAGGER_JITTER = True  # False → 0.5s * sibling_index
ARIADNE_INITIAL_TRANSPORT = "L1_impersonate"
ARIADNE_RESPECT_ROBOTS = "observe"  # observe | obey | ignore
ARIADNE_HONEYPOT_L1_UNVERIFIED = "defer"  # defer | risk_score | follow
ARIADNE_OUTPUT_DIR = "artifacts"
ARIADNE_ENGAGEMENT = None  # path or dict injected at crawl time
ARIADNE_PROXY_URL = None
ARIADNE_PROXY_LIST = None
ARIADNE_IMPERSONATE_PROFILES = None  # None = catalog (filtered by Chromium TLS anchor when L2 on)
ARIADNE_AUTOTHROTTLE_ENABLED = True

# Phase 2 — Browser pool (disabled by default so Phase 1 tests work without Playwright browsers)
ARIADNE_BROWSER_POOL_ENABLED = False
ARIADNE_BROWSER_POOL_SIZE = 4
ARIADNE_BROWSER_CHECKOUT_TIMEOUT = 60.0   # queue wait to acquire a context
ARIADNE_BROWSER_EXECUTION_TIMEOUT = 180.0  # max hold once acquired (CAPTCHA solves)
ARIADNE_BROWSER_MAX_CONTEXTS_SERVED = 5000
ARIADNE_BROWSER_HEADLESS = False  # prefer headed (+ xvfb in Docker) for stealth
ARIADNE_BROWSER_HUMANIZE = True
ARIADNE_CAPTURE_NETWORK = False
ARIADNE_MAX_BODY_SIZE = 2097152  # 2 MiB — apisnoop OOM guard
ARIADNE_SCREENSHOT_MODE = "on_challenge_or_error"

# Phase 3 — L3 unlocker, CAPTCHA, circuit breaker
ARIADNE_UNLOCKER_URL = None  # template; also read from env ARIADNE_UNLOCKER_URL
ARIADNE_CAPTCHA_PROVIDER = None  # null | stub | 2captcha | capsolver
ARIADNE_CIRCUIT_WINDOW = 50
ARIADNE_CIRCUIT_EMPTY_RATIO = 0.50
ARIADNE_CIRCUIT_MIN_SAMPLES = 20
# L3 bills per 200 — fail faster on hollow unlocker pages
ARIADNE_CIRCUIT_L3_WINDOW = 10
ARIADNE_CIRCUIT_L3_EMPTY_RATIO = 0.40
ARIADNE_CIRCUIT_L3_MIN_SAMPLES = 5

# Transparent sticky exit-IP rotation
ARIADNE_TRANSPARENT_IP_WINDOW = 60.0
ARIADNE_TRANSPARENT_IP_MAX_BURNS = 3
ARIADNE_EXIT_IP_CANARY = False  # active echo check (Phase 4 optional)

# robots Disallow: inventory_only | defer | follow
ARIADNE_ROBOTS_HINT_POLICY = "defer"
ARIADNE_ROBOTS_HINT_DELAY = 5.0

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 30.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 4.0

RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524]