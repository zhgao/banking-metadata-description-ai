from __future__ import annotations

import json
from pathlib import Path

from app.config import DEMO_SAMPLES_PATH


class DemoSamples:
    def __init__(self, path: Path = DEMO_SAMPLES_PATH) -> None:
        self.path = path

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data

    def list_samples(self) -> list[dict]:
        return [
            {"name": s.get("name", ""), "description": s.get("description", "")}
            for s in self._load()
        ]

    def get_sample(self, name: str | None = None) -> dict:
        samples = self._load()
        if not samples:
            raise ValueError("No demo samples configured")
        if not name:
            return samples[0].get("payload", {})
        for sample in samples:
            if sample.get("name") == name:
                return sample.get("payload", {})
        raise ValueError(f"Sample '{name}' not found")
