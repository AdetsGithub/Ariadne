# Sitemap & comprehensive URL discovery

Ariadne’s default **map** crawl follows HTML links within `scope` up to `max_depth`.
That is **not** a complete site census. The **discovery** features close common gaps
and emit a union inventory via `ariadne report --sitemap`.

## What “comprehensive” means

| Source | Item | Fetched? |
| --- | --- | --- |
| HTML pages (link follow) | `PageItem` | Yes |
| `sitemap.xml` / robots `Sitemap:` | `UrlCandidateItem` (+ scheduled PageItem) | Yes (in-scope) |
| Static assets | `AssetItem` | HEAD/GET when enabled |
| Cross-host `<a href>` | `OutboundLinkItem` | **Never** |
| Download / HTTP failures | `FailedUrlItem` | Attempted |
| JS path heuristics | `UrlCandidateItem` | Optional schedule |
| GET form actions | `UrlCandidateItem` + seed | Yes (in-scope) |
| Browser XHR (apisnoop) | `EndpointItem` | Via L2 |

**Residual gaps (not claimed):** opaque SPA client routers, auth-only trees, search
query-parameter explosion, URLs never linked and absent from sitemaps.

## Engagement YAML

```yaml
scope:
  max_depth: null   # or -1 / unlimited — no link-depth cap

crawl:
  discovery:
    sitemaps: true
    include_assets: false
    asset_method: head      # head | get | none
    outbound_links: true
    record_failures: true
    record_http_errors: true
    js_route_hints: false
    form_action_seeds: true
```

Defaults keep crawls light: sitemaps/outbound/failures on; assets and JS hints off
until you opt in.

## Artifacts

Under `{output.dir}/{engagement.id}/`:

- `PageItem.ndjson`, `FormItem.ndjson`, …
- `AssetItem.ndjson`, `OutboundLinkItem.ndjson`, `FailedUrlItem.ndjson`, `UrlCandidateItem.ndjson`
- After `ariadne report DIR --sitemap`: `sitemap.jsonl` + `sitemap.md`

## Operator sequence

1. `map` with discovery enabled (and optional `max_depth: null`).
2. Inspect `FailedUrlItem` / re-seed gaps.
3. Targeted `apisnoop` for API-heavy areas.
4. `ariadne report … --sitemap` for the union inventory.

See also: [CONFIGURATION.md](./CONFIGURATION.md), [OPERATOR.md](./OPERATOR.md).
