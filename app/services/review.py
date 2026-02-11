from __future__ import annotations

import json
from datetime import datetime, timezone

from app import models
from app.config import DICTIONARY_PATH, REVIEWS_PATH


class ReviewStore:
    def save(self, request: models.ReviewRequest) -> models.ReviewResponse:
        record = models.ReviewRecord(
            timestamp=datetime.now(timezone.utc),
            table_name=request.table_name,
            reviewer=request.reviewer,
            decisions=request.decisions,
        )

        with REVIEWS_PATH.open("a", encoding="utf-8") as f:
            f.write(record.model_dump_json())
            f.write("\n")

        self._save_dictionary_entries(request)

        approved = sum(1 for d in request.decisions if d.action == "approved")
        edited = sum(1 for d in request.decisions if d.action == "edited")
        rejected = sum(1 for d in request.decisions if d.action == "rejected")

        return models.ReviewResponse(
            status="saved",
            approved_count=approved,
            edited_count=edited,
            rejected_count=rejected,
        )

    def read_all(self) -> list[dict]:
        if not REVIEWS_PATH.exists():
            return []
        records: list[dict] = []
        with REVIEWS_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records

    def read_dictionary(self) -> list[dict]:
        if not DICTIONARY_PATH.exists():
            return []
        records: list[dict] = []
        with DICTIONARY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
        return records

    def _save_dictionary_entries(self, request: models.ReviewRequest) -> None:
        generated_map = {c.column_name: c for c in request.generated_columns}
        entries: list[models.DictionaryEntry] = []
        now = datetime.now(timezone.utc)

        for decision in request.decisions:
            generated = generated_map.get(decision.column_name)
            if decision.action == "rejected" or generated is None:
                continue

            desc = generated.column_description
            source = "approved"
            if decision.action == "edited" and decision.edited_description:
                desc = decision.edited_description.strip() or generated.column_description
                source = "edited"

            entries.append(
                models.DictionaryEntry(
                    timestamp=now,
                    table_name=request.table_name,
                    column_name=decision.column_name,
                    column_description=desc,
                    business_meaning=generated.business_meaning,
                    pii_flag=generated.pii_flag,
                    confidence=generated.confidence,
                    source=source,
                )
            )

        if not entries:
            return

        with DICTIONARY_PATH.open("a", encoding="utf-8") as f:
            for entry in entries:
                f.write(entry.model_dump_json())
                f.write("\n")
