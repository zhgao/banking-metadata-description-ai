from __future__ import annotations

from pathlib import Path

import yaml

from app.config import BANKING_TERMS_PATH


class BankingDomainKnowledge:
    def __init__(self, path: Path = BANKING_TERMS_PATH) -> None:
        self.path = path
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"terms": {}, "pii_keywords": []}
        with self.path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {
            "terms": data.get("terms", {}),
            "pii_keywords": data.get("pii_keywords", []),
        }

    def match_terms(self, text: str) -> dict[str, str]:
        source = text.lower()
        matches: dict[str, str] = {}
        for term, meaning in self._data["terms"].items():
            if term.lower() in source:
                matches[term] = meaning
        return matches

    def pii_keywords(self) -> list[str]:
        return list(self._data["pii_keywords"])
