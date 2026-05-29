"""Transport-aware dupefilter — L1 and L2 of same URL are distinct fingerprints."""

from __future__ import annotations

import hashlib

from scrapy.dupefilters import RFPDupeFilter
from scrapy.utils.python import to_bytes
from scrapy.utils.request import fingerprint as scrapy_fingerprint


class TransportAwareDupeFilter(RFPDupeFilter):
    """Include transport_mode (+ clearance_epoch) so L2 escalations are not dropped."""

    def request_fingerprint(self, request):
        fp = scrapy_fingerprint(request)
        mode = request.meta.get("transport_mode", "L0_http")
        epoch = request.meta.get("clearance_epoch", 0)
        salted = hashlib.sha1()
        salted.update(to_bytes(fp if isinstance(fp, (bytes, bytearray)) else str(fp)))
        salted.update(b"|")
        salted.update(to_bytes(str(mode)))
        salted.update(b"|")
        salted.update(to_bytes(str(epoch)))
        return salted.hexdigest()
