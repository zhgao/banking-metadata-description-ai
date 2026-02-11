# Banking Data Dictionary AI (Hackathon MVP)

FastAPI service that generates business descriptions for banking table/column metadata, validates quality/PII risk, and supports human review decisions.

## Features
- **CSV flow (primary):** Input CSV with `table_name` and `column_name` → output same CSV with `column_description` added.
  - `POST /v1/descriptions/generate-csv` — upload a CSV file; returns CSV with extra column `column_description`. **LLM-only** (requires `OPENAI_API_KEY`).
- `POST /v1/descriptions/generate` (JSON, optional)
  - **LLM-only** generation for table + column descriptions (requires `OPENAI_API_KEY`).
- `POST /v1/descriptions/validate`
  - Confidence threshold checks.
  - PII summary and risk level.
- `POST /v1/reviews/submit`
  - Store reviewer approvals/edits/rejections.
- `GET /v1/reviews`
  - Fetch review history for demo.
- `GET /v1/dictionary/export.csv`
  - Download approved/edited dictionary entries as CSV.
- `GET /v1/demo/samples`
  - List available demo datasets.
- `GET /v1/demo/sample?name=customer_account`
  - Load a sample payload in one click.
- `GET /`
  - Browser demo UI for full workflow.

## Project Structure
- `app/main.py` - FastAPI routes
- `app/models.py` - Request/response schemas
- `app/services/generator.py` - Rule + optional LLM generation logic
- `app/services/validator.py` - Validation and quality checks
- `app/services/review.py` - JSONL-based review storage
- `data/banking_terms.yaml` - Banking terms + PII keywords
- `tests/test_api.py` - End-to-end API smoke test

## Run Locally

**Python version:** Use Python 3.12 or 3.13. Python 3.14 is not yet supported by pydantic-core (no pre-built wheels; source build fails).

```bash
python3.13 -m venv .venv   # or python3.12
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Health check:
```bash
curl http://127.0.0.1:8000/health
```

Open demo UI:
```bash
open http://127.0.0.1:8000/
```

Upload a CSV with headers `table_name` and `column_name` (e.g. `data/sample_columns.csv`); click **Generate column descriptions**; download the result CSV with `column_description` added.

## Example API Calls
**CSV (add column descriptions):**
```bash
curl -X POST http://127.0.0.1:8000/v1/descriptions/generate-csv \
  -F "file=@data/sample_columns.csv" \
  -o output_with_descriptions.csv
```

**JSON generate:**
```bash
curl -X POST http://127.0.0.1:8000/v1/descriptions/generate \
  -H "Content-Type: application/json" \
  -d '{
    "table_name":"customer_account",
    "table_context":"Retail banking account master",
    "columns":[
      {
        "column_name":"acct_open_dt",
        "data_type":"date",
        "nullable":false,
        "constraints":["not_null"],
        "sample_values":["2023-06-01","2021-11-15"]
      },
      {
        "column_name":"kyc_status_cd",
        "data_type":"varchar(10)",
        "nullable":false,
        "constraints":["check enum"],
        "sample_values":["VERIFIED","PENDING"]
      }
    ]
  }'
```

Validate:
```bash
curl -X POST http://127.0.0.1:8000/v1/descriptions/validate \
  -H "Content-Type: application/json" \
  -d '{
    "table_name":"customer_account",
    "generated_payload": { "table_description":"...", "columns":[], "model_version":"rules-v1", "needs_review":false }
  }'
```

## Optional LLM refinement
Set environment variables before starting the app to use the LLM for column descriptions (CSV and JSON flows):
```bash
export OPENAI_API_KEY="your_key"
export OPENAI_MODEL="gpt-4o-mini"
```
When unset, the system falls back to deterministic rule-based generation.

## Notes for Hackathon Demo
- Use `Load Sample` in UI to prefill a banking dataset instantly.
- Keep sample values masked.
- Show auto-generation, then validation, then reviewer submit from the web UI.
- Download the approved dictionary CSV from `/v1/dictionary/export.csv`.
- Track acceptance/edit rates from `reviews.jsonl` and approved entries from `dictionary.jsonl`.
