"""Light validation pipeline."""

from __future__ import annotations

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem


class ValidatePipeline:
    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        if "url" in adapter.field_names() and not adapter.get("url"):
            raise DropItem("missing url")
        if "host" in adapter.field_names() and not adapter.get("host") and not adapter.get("path"):
            # RobotsHintItem should have host+path
            if adapter.get("directive"):
                raise DropItem("invalid robots hint")
        return item
