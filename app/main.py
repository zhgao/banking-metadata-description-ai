from __future__ import annotations

import csv
import io

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

from app import models
from app.services.domain import BankingDomainKnowledge
from app.services.generator import DescriptionGenerator
from app.services.review import ReviewStore
from app.services.samples import DemoSamples
from app.services.validator import DescriptionValidator

app = FastAPI(title="Banking Data Dictionary AI", version="1.0.0")

knowledge = BankingDomainKnowledge()
generator = DescriptionGenerator(knowledge)
validator = DescriptionValidator()
review_store = ReviewStore()
demo_samples = DemoSamples()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/descriptions/generate", response_model=models.GenerateResponse)
def generate_descriptions(request: models.GenerateRequest) -> models.GenerateResponse:
    try:
        result = generator.generate(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    needs_review = any(c.confidence < 0.75 for c in result.columns)
    return models.GenerateResponse(
        table_description=result.table_description,
        columns=result.columns,
        model_version=result.model_version,
        needs_review=needs_review,
    )


@app.post("/v1/descriptions/generate-csv")
def generate_descriptions_csv(file: UploadFile = File(...)) -> StreamingResponse:
    """Accept a CSV with table_name and column_name; return same CSV with column_description added."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a CSV file")
    content = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    rows_list = list(reader)
    if not rows_list:
        raise HTTPException(status_code=400, detail="CSV has no data rows")
    fieldnames = reader.fieldnames or []
    if "table_name" not in fieldnames or "column_name" not in fieldnames:
        raise HTTPException(
            status_code=400,
            detail="CSV must have headers: table_name, column_name",
        )
    row_tuples = [
        (row["table_name"].strip(), row["column_name"].strip())
        for row in rows_list
    ]
    try:
        descriptions = generator.generate_column_descriptions_for_rows(row_tuples)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    out_headers = [f for f in fieldnames if f != "column_description"] + ["column_description"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=out_headers, extrasaction="ignore")
    writer.writeheader()
    for row, col_desc in zip(rows_list, descriptions, strict=True):
        row["column_description"] = col_desc
        writer.writerow(row)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=descriptions.csv"},
    )


@app.post("/v1/descriptions/validate", response_model=models.ValidateResponse)
def validate_descriptions(request: models.ValidateRequest) -> models.ValidateResponse:
    return validator.validate(request)


@app.post("/v1/reviews/submit", response_model=models.ReviewResponse)
def submit_review(request: models.ReviewRequest) -> models.ReviewResponse:
    return review_store.save(request)


@app.get("/v1/reviews")
def get_reviews() -> list[dict]:
    return review_store.read_all()


@app.get("/v1/dictionary")
def get_dictionary() -> list[dict]:
    return review_store.read_dictionary()


@app.get("/v1/dictionary/export.csv")
def export_dictionary_csv() -> StreamingResponse:
    rows = review_store.read_dictionary()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "timestamp",
            "table_name",
            "column_name",
            "column_description",
            "business_meaning",
            "pii_flag",
            "confidence",
            "source",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.get("timestamp", ""),
                row.get("table_name", ""),
                row.get("column_name", ""),
                row.get("column_description", ""),
                row.get("business_meaning", ""),
                row.get("pii_flag", False),
                row.get("confidence", ""),
                row.get("source", ""),
            ]
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=approved_dictionary.csv"},
    )


@app.get("/v1/demo/samples")
def list_demo_samples() -> list[dict]:
    return demo_samples.list_samples()


@app.get("/v1/demo/sample")
def get_demo_sample(name: str | None = None) -> dict:
    try:
        return demo_samples.get_sample(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
def demo_ui() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Banking Data Dictionary AI - Demo</title>
  <style>
    :root{
      --bg:#f5f4ef;
      --ink:#19222b;
      --card:#ffffff;
      --accent:#005d5d;
      --muted:#5a6772;
      --line:#d7d8d3;
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color:var(--ink);
      background:
        radial-gradient(circle at 15% 10%, #d7ece4 0%, transparent 30%),
        radial-gradient(circle at 90% 80%, #f0dcc7 0%, transparent 35%),
        var(--bg);
      min-height:100vh;
    }
    .wrap{max-width:1080px;margin:24px auto;padding:16px}
    h1{margin:0 0 4px;font-size:30px}
    .sub{color:var(--muted);margin:0 0 18px}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
    .card{
      background:var(--card);
      border:1px solid var(--line);
      border-radius:14px;
      padding:14px;
      box-shadow:0 8px 24px rgba(0,0,0,.05);
    }
    label{display:block;font-size:13px;color:var(--muted);margin-bottom:6px}
    input,textarea{
      width:100%;
      border:1px solid #bcc4cc;
      border-radius:10px;
      padding:10px;
      font-size:14px;
      margin-bottom:10px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    textarea{min-height:132px;resize:vertical}
    button,a.btn{
      background:var(--accent);
      color:#fff;
      border:none;
      border-radius:10px;
      padding:10px 14px;
      font-weight:600;
      cursor:pointer;
      text-decoration:none;
      display:inline-block;
      margin-right:8px;
      margin-top:6px;
    }
    pre{
      background:#0f1720;
      color:#d4ffe0;
      border-radius:10px;
      padding:10px;
      min-height:280px;
      overflow:auto;
      font-size:12px;
    }
    .full{grid-column:1 / -1}
    @media (max-width:900px){.grid{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Banking Data Dictionary AI</h1>
    <p class="sub">Upload CSV (table_name, column_name) → download CSV with column_description</p>
    <div class="grid">
      <div class="card">
        <label>CSV input (must have headers: table_name, column_name)</label>
        <input type="file" id="csvFile" accept=".csv" />
        <button onclick="runGenerateCsv()">Generate column descriptions</button>
        <span id="csvStatus"></span>
      </div>
      <div class="card">
        <label>Output CSV (with column_description)</label>
        <pre id="output"></pre>
        <a id="downloadLink" class="btn" style="display:none" download="descriptions.csv">Download CSV</a>
      </div>
      <div class="card full">
        <label>Optional: Generate Request JSON (legacy)</label>
        <textarea id="generatePayload">{
  "table_name": "customer_account",
  "table_context": "Retail banking account master",
  "columns": [
    {
      "column_name": "acct_open_dt",
      "data_type": "date",
      "nullable": false,
      "constraints": ["not_null"],
      "sample_values": ["2023-06-01", "2021-11-15"]
    },
    {
      "column_name": "customer_email",
      "data_type": "varchar(255)",
      "nullable": true,
      "constraints": [],
      "sample_values": ["masked@example.com"]
    }
  ]
}</textarea>
        <label>Reviewer Email</label>
        <input id="reviewer" value="judge@hackathon.dev" />
        <label>Demo Sample Name</label>
        <input id="sampleName" value="customer_account" />
        <button onclick="loadSample()">Load Sample</button>
        <button onclick="runGenerate()">Generate</button>
        <button onclick="runValidate()">Validate</button>
        <button onclick="submitReview()">Submit Review</button>
        <a class="btn" href="/v1/dictionary/export.csv" target="_blank">Download CSV</a>
      </div>
      <div class="card full">
        <label>Review Decisions JSON (approved/edited/rejected)</label>
        <textarea id="reviewPayload">{
  "decisions": [
    {"column_name":"acct_open_dt","action":"approved"},
    {"column_name":"customer_email","action":"edited","edited_description":"Customer email used for digital notifications and authentication workflows."}
  ]
}</textarea>
      </div>
    </div>
  </div>
  <script>
    let latestGenerated = null;
    const output = document.getElementById("output");

    function show(obj){
      output.textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
    }

    async function loadSample(){
      const name = encodeURIComponent(document.getElementById("sampleName").value.trim());
      const query = name ? "?name=" + name : "";
      const res = await fetch("/v1/demo/sample" + query);
      const data = await res.json();
      if(!res.ok){ show(data); return; }
      document.getElementById("generatePayload").value = JSON.stringify(data, null, 2);
      latestGenerated = null;
      show({ message: "Sample loaded", sample: name || "default" });
    }

    async function runGenerateCsv(){
      const input = document.getElementById("csvFile");
      const status = document.getElementById("csvStatus");
      const link = document.getElementById("downloadLink");
      if(!input.files || !input.files[0]){ status.textContent = "Select a CSV file."; return; }
      status.textContent = "Generating…";
      link.style.display = "none";
      const form = new FormData();
      form.append("file", input.files[0]);
      const res = await fetch("/v1/descriptions/generate-csv", { method: "POST", body: form });
      const text = await res.text();
      if(!res.ok){
        status.textContent = "";
        try { const err = JSON.parse(text); show(err.detail || text); } catch(_) { show(text); }
        return;
      }
      status.textContent = "Done.";
      show(text);
      const blob = new Blob([text], { type: "text/csv" });
      link.href = URL.createObjectURL(blob);
      link.style.display = "inline-block";
    }

    async function runGenerate(){
      const body = JSON.parse(document.getElementById("generatePayload").value);
      const res = await fetch("/v1/descriptions/generate", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(body)
      });
      const data = await res.json();
      latestGenerated = data;
      show(data);
    }

    async function runValidate(){
      if(!latestGenerated){ show("Run Generate first."); return; }
      const body = {
        table_name: JSON.parse(document.getElementById("generatePayload").value).table_name,
        generated_payload: latestGenerated
      };
      const res = await fetch("/v1/descriptions/validate", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(body)
      });
      show(await res.json());
    }

    async function submitReview(){
      if(!latestGenerated){ show("Run Generate first."); return; }
      const table = JSON.parse(document.getElementById("generatePayload").value).table_name;
      const reviewDecisions = JSON.parse(document.getElementById("reviewPayload").value).decisions;
      const body = {
        table_name: table,
        reviewer: document.getElementById("reviewer").value,
        decisions: reviewDecisions,
        generated_columns: latestGenerated.columns || []
      };
      const res = await fetch("/v1/reviews/submit", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify(body)
      });
      show(await res.json());
    }
  </script>
</body>
</html>
"""
