from __future__ import annotations

import json
from dataclasses import dataclass

from app import models
from app.config import MAX_SAMPLE_VALUES, OPENAI_API_KEY, OPENAI_MODEL
from app.services.domain import BankingDomainKnowledge
from app.services.name_parser import humanize_identifier, split_identifier

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore[assignment]


@dataclass
class GeneratorResult:
    table_description: str
    columns: list[models.ColumnDescription]
    model_version: str


class DescriptionGenerator:
    def __init__(self, knowledge: BankingDomainKnowledge) -> None:
        self.knowledge = knowledge
        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY and OpenAI else None

    def generate(self, request: models.GenerateRequest) -> GeneratorResult:
        table_description = self._generate_table_description(request)
        columns = [self._generate_column(request.table_name, c) for c in request.columns]

        # Prefer LLM when available, but keep deterministic fallback for local/demo use.
        generated = self._generate_with_llm(request) if self.client else None
        if generated:
            return generated

        return GeneratorResult(
            table_description=table_description,
            columns=columns,
            model_version="rules-v1",
        )

    def generate_column_descriptions_for_rows(
        self, rows: list[tuple[str, str]]
    ) -> list[str]:
        """Generate only column_description for each (table_name, column_name) pair."""
        llm_descriptions = self._generate_column_descriptions_with_llm(rows) if self.client else None
        if llm_descriptions is not None and len(llm_descriptions) == len(rows):
            return llm_descriptions
        return [self._rule_column_description(table_name, column_name) for table_name, column_name in rows]

    def _generate_column_descriptions_with_llm(
        self, rows: list[tuple[str, str]]
    ) -> list[str] | None:
        """Call LLM to generate one column_description per (table_name, column_name). Returns list in same order, or None on failure."""
        if not self.client or not rows:
            return None
        payload = [
            {"table_name": table_name, "column_name": column_name}
            for table_name, column_name in rows
        ]
        system = (
            "You are a banking data dictionary expert. Given a list of table_name and column_name pairs, "
            "return a JSON object with a single key 'descriptions': an array of strings, one per row in the same order. "
            "Each string is a concise business-facing column description (1-2 sentences) for that column in that table. "
            "Use banking terminology and be consistent. Output only valid JSON, no markdown."
        )
        try:
            completion = self.client.responses.create(
                model=OPENAI_MODEL,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                temperature=0.1,
            )
        except Exception:
            return None
        content = completion.output_text
        try:
            parsed = json.loads(content)
            descriptions = parsed.get("descriptions")
            if not isinstance(descriptions, list) or len(descriptions) != len(rows):
                return None
            return [str(d).strip() for d in descriptions]
        except Exception:
            return None

    def _rule_column_description(self, table_name: str, column_name: str) -> str:
        return f"{humanize_identifier(column_name).capitalize()} in `{table_name}`."

    def _generate_table_description(self, request: models.GenerateRequest) -> str:
        base = f"Stores {humanize_identifier(request.table_name)} attributes for banking operations"
        if request.table_context:
            base += f". Context: {request.table_context.strip()}."
        else:
            base += "."
        return base

    def _generate_column(self, table_name: str, col: models.ColumnInput) -> models.ColumnDescription:
        readable = humanize_identifier(col.column_name)
        dtype = col.data_type.lower()

        description = f"{readable.capitalize()} in `{table_name}`."
        meaning = "Used in analytics and operational reporting."

        if "date" in dtype or any(tok in col.column_name.lower() for tok in ["date", "dt"]):
            meaning = "Represents a lifecycle event date for reporting and controls."
        if "amount" in readable or "amt" in col.column_name.lower() or any(tok in dtype for tok in ["decimal", "numeric", "money"]):
            meaning = "Represents a monetary value used in transaction and balance calculations."
        if any(tok in col.column_name.lower() for tok in ["status", "code", "cd"]):
            meaning = "Represents a business process status or coded classification."

        pii_flag = self._is_pii(col.column_name)
        confidence = self._estimate_confidence(col)

        if pii_flag:
            meaning = "Contains potentially sensitive customer information and should follow data protection controls."

        return models.ColumnDescription(
            column_name=col.column_name,
            column_description=description,
            business_meaning=meaning,
            pii_flag=pii_flag,
            confidence=confidence,
        )

    def _is_pii(self, column_name: str) -> bool:
        lowered = column_name.lower()
        default_pii = {
            "name",
            "ssn",
            "email",
            "phone",
            "mobile",
            "dob",
            "birth",
            "address",
            "passport",
            "tax_id",
        }
        keywords = default_pii | set(k.lower() for k in self.knowledge.pii_keywords())
        return any(k in lowered for k in keywords)

    def _estimate_confidence(self, col: models.ColumnInput) -> float:
        score = 0.55
        tokens = split_identifier(col.column_name)
        if len(tokens) >= 2:
            score += 0.1
        if col.constraints:
            score += 0.1
        if col.sample_values:
            score += 0.15
        if col.data_type:
            score += 0.1
        return max(0.0, min(0.99, round(score, 2)))

    def _refine_with_llm(
        self,
        request: models.GenerateRequest,
        table_description: str,
        columns: list[models.ColumnDescription],
    ) -> GeneratorResult | None:
        if not self.client:
            return None

        prompt = {
            "table_name": request.table_name,
            "table_context": request.table_context,
            "table_description": table_description,
            "columns": [
                {
                    "column_name": c.column_name,
                    "column_description": c.column_description,
                    "business_meaning": c.business_meaning,
                    "pii_flag": c.pii_flag,
                    "confidence": c.confidence,
                    "matched_terms": self.knowledge.match_terms(c.column_name),
                    "metadata": {
                        "data_type": src.data_type,
                        "nullable": src.nullable,
                        "constraints": src.constraints,
                        "sample_values": src.sample_values[:MAX_SAMPLE_VALUES],
                    },
                }
                for c, src in zip(columns, request.columns, strict=True)
            ],
        }

        try:
            completion = self.client.responses.create(
                model=OPENAI_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are a banking data dictionary expert. Return strict JSON with keys "
                            "table_description and columns. Each column must include column_name, "
                            "column_description, business_meaning, pii_flag, confidence."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt)},
                ],
                temperature=0.1,
            )
        except Exception:
            return None

        content = completion.output_text
        try:
            parsed = json.loads(content)
            parsed_columns = [models.ColumnDescription(**c) for c in parsed["columns"]]
            return GeneratorResult(
                table_description=parsed["table_description"],
                columns=parsed_columns,
                model_version=f"{OPENAI_MODEL}-refined",
            )
        except Exception:
            return None

    def _generate_with_llm(self, request: models.GenerateRequest) -> GeneratorResult | None:
        """Generate table_description and columns directly from the LLM (no rule-based seed)."""
        if not self.client:
            return None

        prompt = {
            "table_name": request.table_name,
            "table_context": request.table_context,
            "columns": [
                {
                    "column_name": c.column_name,
                    "matched_terms": self.knowledge.match_terms(c.column_name),
                    "metadata": {
                        "data_type": c.data_type,
                        "nullable": c.nullable,
                        "constraints": c.constraints,
                        "sample_values": c.sample_values[:MAX_SAMPLE_VALUES],
                    },
                }
                for c in request.columns
            ],
        }

        try:
            completion = self.client.responses.create(
                model=OPENAI_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are a banking data dictionary expert. Return strict JSON with keys "
                            "table_description and columns. Each column must include column_name, "
                            "column_description, business_meaning, pii_flag, confidence."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt)},
                ],
                temperature=0.1,
            )
        except Exception:
            return None

        content = completion.output_text
        try:
            parsed = json.loads(content)
            parsed_columns = [models.ColumnDescription(**c) for c in parsed["columns"]]
            return GeneratorResult(
                table_description=parsed["table_description"],
                columns=parsed_columns,
                model_version=f"{OPENAI_MODEL}-generated",
            )
        except Exception:
            return None
