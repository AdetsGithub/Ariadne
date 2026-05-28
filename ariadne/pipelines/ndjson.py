"""NDJSON export pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from itemadapter import ItemAdapter


class NdjsonExportPipeline:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self._handles: dict[str, any] = {}

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings.get("ARIADNE_OUTPUT_DIR", "artifacts"))

    def open_spider(self, spider):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        meta_path = self.output_dir / "engagement.json"
        eng = spider.settings.get("ARIADNE_ENGAGEMENT")
        if eng:
            meta_path.write_text(json.dumps(eng, indent=2), encoding="utf-8")

    def close_spider(self, spider):
        for fh in self._handles.values():
            fh.close()

    def process_item(self, item, spider):
        name = item.__class__.__name__
        path = self.output_dir / f"{name}.ndjson"
        if name not in self._handles:
            self._handles[name] = path.open("a", encoding="utf-8")
        record = ItemAdapter(item).asdict()
        record["_item"] = name
        self._handles[name].write(json.dumps(record, default=str) + "\n")
        self._handles[name].flush()
        return item
