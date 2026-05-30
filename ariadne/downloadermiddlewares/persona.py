"""Apply profile-derived persona headers to every request."""

from __future__ import annotations

from scrapy.http import Request

from ariadne.stealth import Persona


class PersonaHeadersMiddleware:
    def process_request(self, request: Request, spider):
        if request.meta.get("ariadne_exit_ip_canary"):
            # Bare canary headers only — never overlay target persona / Referer / Sec-CH-UA
            return None
        pdata = request.meta.get("ariadne_persona")
        if not pdata:
            return None
        persona = Persona(**pdata)
        referer = request.headers.get("Referer")
        if isinstance(referer, bytes):
            referer = referer.decode()
        elif isinstance(referer, (list, tuple)) and referer:
            referer = referer[0].decode() if isinstance(referer[0], bytes) else str(referer[0])
        else:
            referer = request.meta.get("referer")
        fetch_site = "same-origin" if referer else "none"
        for k, v in persona.headers(referer=referer, fetch_site=fetch_site).items():
            # Don't overwrite explicitly set Referer if already present
            if k == "Referer" and request.headers.get("Referer"):
                continue
            request.headers[k] = v
        return None
