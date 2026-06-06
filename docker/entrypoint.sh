#!/usr/bin/env bash
# Run Ariadne under Xvfb so Playwright can use headed mode inside Docker.
# Cloudflare/Akamai often flag --headless=new; headed+Xvfb is the stealth path.
#
# IMPORTANT: do not bare `exec` the child without a reaper. Scrapy asyncio shutdown
# can sever Playwright IPC before browser.close() finishes, leaving orphan Chromium.
# This wrapper traps EXIT/INT/TERM and kills the process group / children.
set -euo pipefail

cleanup() {
  local code=$?
  # Kill direct children (xvfb-run, node, chrome, …)
  pkill -P $$ 2>/dev/null || true
  # Best-effort: anything left in our process group
  if [[ -n "${ARIADNE_PGID:-}" ]]; then
    kill -TERM -"${ARIADNE_PGID}" 2>/dev/null || true
  fi
  # Named fallbacks if IPC died first
  pkill -f "[c]hromium.*--remote-debugging-port" 2>/dev/null || true
  pkill -f "[c]hrome.*--remote-debugging-port" 2>/dev/null || true
  exit "${code}"
}
trap cleanup EXIT INT TERM

# Own process group so kill(-pgid) can reap the tree
set -m
ARIADNE_PGID=$$
export ARIADNE_PGID

if [[ "${ARIADNE_USE_XVFB:-1}" == "1" ]]; then
  xvfb-run -a --server-args="-screen 0 1920x1080x24" "$@" &
else
  "$@" &
fi
wait $! || exit $?
