from __future__ import annotations

from app import models
from app.config import CONFIDENCE_THRESHOLD


class DescriptionValidator:
    def validate(self, request: models.ValidateRequest) -> models.ValidateResponse:
        issues: list[models.ValidationIssue] = []

        payload = request.generated_payload
        if not payload.table_description.strip():
            issues.append(models.ValidationIssue(code="EMPTY_TABLE_DESC", message="Table description is empty"))

        pii_columns: list[str] = []
        for col in payload.columns:
            if not col.column_description.strip():
                issues.append(
                    models.ValidationIssue(
                        code="EMPTY_COLUMN_DESC",
                        message="Column description is empty",
                        target=col.column_name,
                    )
                )
            if col.confidence < CONFIDENCE_THRESHOLD:
                issues.append(
                    models.ValidationIssue(
                        code="LOW_CONFIDENCE",
                        message=f"Confidence below threshold {CONFIDENCE_THRESHOLD}",
                        target=col.column_name,
                    )
                )
            if col.pii_flag:
                pii_columns.append(col.column_name)

        risk = "low"
        if len(pii_columns) >= 3:
            risk = "high"
        elif pii_columns:
            risk = "medium"

        return models.ValidateResponse(
            valid=len(issues) == 0,
            issues=issues,
            pii_summary=models.PiiSummary(pii_columns=pii_columns, risk_level=risk),
        )
