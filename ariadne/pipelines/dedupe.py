"""In-run item dedupe by type+url(+path)."""

from __future__ import annotations

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem


class DedupePipeline:
    def __init__(self):
        self.seen: set[str] = set()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        key = "|".join(
            str(adapter.get(k) or "")
            for k in ("url", "host", "path", "directive", "action", "type")
        )
        key = f"{item.__class__.__name__}:{key}"
        if key in self.seen:
            raise DropItem(f"duplicate {key}")
        self.seen.add(key)
        return item
