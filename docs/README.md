# Ariadne documentation

| Doc | Audience | Contents |
| --- | --- | --- |
| [OPERATOR.md](./OPERATOR.md) | Operators / pentesters | Install, engagement lifecycle, CLI, Docker, artifacts, kill-switch |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Engineers / reviewers | Transport modes, Session Sync, middleware order, traps map |
| [CONFIGURATION.md](./CONFIGURATION.md) | Operators / engineers | Engagement YAML schema, `ARIADNE_*` settings, env vars |
| [SITEMAP.md](./SITEMAP.md) | Operators / engineers | Comprehensive URL discovery, artifact union, residual SPA gaps |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | Operators | Clearance invalidation, circuit trips, zombies, pack crypto |
| [../SPEC.md](../SPEC.md) | Spec owners | Normative MUST/MUST NOT (v1.4.3) |
| [../engagements/example.yaml](../engagements/example.yaml) | Operators | Minimal valid engagement |
| [../engagements/extended.example.yaml](../engagements/extended.example.yaml) | Operators | Annotated production-shaped template |

### Reading order

1. Root [README.md](../README.md) — install & authorize  
2. **OPERATOR.md** — run an engagement end-to-end  
3. **CONFIGURATION.md** — tune YAML / settings  
4. **SITEMAP.md** — when you need more than HTML link-follow inventory  
5. **ARCHITECTURE.md** — understand failure modes before changing code  
6. **SPEC.md** — when implementing or reviewing Phase 4+ work  

### Spec version

Documentation in this folder matches **SPEC v1.4.3** (Phase 1–3 shipped; Phase 4 edge mechanics locked).
