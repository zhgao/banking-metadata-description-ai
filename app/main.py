from __future__ import annotations

import csv
import io
from statistics import mean

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

from app import models
from app.config import OLLAMA_COMPARE_MODEL, OLLAMA_MODEL, OPENAI_MODEL, PREFER_LOCAL_LLM
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

BANKING_KEYWORDS = {
    "account",
    "transaction",
    "compliance",
    "kyc",
    "aml",
    "customer",
    "loan",
    "interest",
    "apr",
    "balance",
    "payment",
    "risk",
}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _parse_uploaded_csv(file: UploadFile) -> tuple[list[str], list[dict], list[tuple[str, str]]]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a CSV file")

    content = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    rows_list = list(reader)
    if not rows_list:
        raise HTTPException(status_code=400, detail="CSV has no data rows")

    fieldnames = reader.fieldnames or []
    if "table_name" not in fieldnames or "column_name" not in fieldnames:
        raise HTTPException(status_code=400, detail="CSV must have headers: table_name, column_name")

    row_tuples = [
        (row["table_name"].strip(), row["column_name"].strip())
        for row in rows_list
    ]
    return fieldnames, rows_list, row_tuples


def _build_output_csv(fieldnames: list[str], rows_list: list[dict], descriptions: list[str]) -> str:
    out_headers = [f for f in fieldnames if f != "column_description"] + ["column_description"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=out_headers, extrasaction="ignore")
    writer.writeheader()
    for row, col_desc in zip(rows_list, descriptions, strict=True):
        row_copy = dict(row)
        row_copy["column_description"] = col_desc
        writer.writerow(row_copy)
    output.seek(0)
    return output.getvalue()


def _score_descriptions(descriptions: list[str]) -> dict:
    if not descriptions:
        return {"score": 0.0, "specificity": 0.0, "banking_relevance": 0.0, "generic_penalty": 1.0}

    def has_banking_terms(text: str) -> float:
        low = text.lower()
        return 1.0 if any(k in low for k in BANKING_KEYWORDS) else 0.0

    def specificity(text: str) -> float:
        words = max(1, len(text.split()))
        return min(words / 18.0, 1.0)

    def is_generic(text: str) -> float:
        low = text.lower()
        generic_markers = [
            " in `",
            "used in analytics",
            "used for analytics",
            "field in",
            "column in",
        ]
        return 1.0 if any(g in low for g in generic_markers) else 0.0

    specificity_score = mean(specificity(d) for d in descriptions)
    banking_relevance = mean(has_banking_terms(d) for d in descriptions)
    generic_penalty = mean(is_generic(d) for d in descriptions)
    total = ((0.45 * banking_relevance) + (0.45 * specificity_score) + (0.10 * (1.0 - generic_penalty))) * 100.0
    return {
        "score": round(total, 2),
        "specificity": round(specificity_score, 3),
        "banking_relevance": round(banking_relevance, 3),
        "generic_penalty": round(generic_penalty, 3),
    }


def _compare_models(model_a: str, model_b: str, descriptions_a: list[str], descriptions_b: list[str]) -> dict:
    metrics_a = _score_descriptions(descriptions_a)
    metrics_b = _score_descriptions(descriptions_b)
    winner = model_a if metrics_a["score"] >= metrics_b["score"] else model_b
    if winner == model_a:
        reason = f"{model_a} has stronger banking relevance/specificity score ({metrics_a['score']} vs {metrics_b['score']})."
    else:
        reason = f"{model_b} has stronger banking relevance/specificity score ({metrics_b['score']} vs {metrics_a['score']})."
    return {
        "winner_model": winner,
        "reason": reason,
        "model_a_metrics": metrics_a,
        "model_b_metrics": metrics_b,
    }


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
    fieldnames, rows_list, row_tuples = _parse_uploaded_csv(file)
    try:
        generation = generator.generate_column_descriptions_for_rows(row_tuples)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    csv_output = _build_output_csv(fieldnames, rows_list, generation.descriptions)
    return StreamingResponse(
        iter([csv_output]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=descriptions.csv",
            "X-LLM-Provider": generation.provider,
            "X-LLM-Model": generation.model_version,
            "X-LLM-Used": "true" if generation.used_llm else "false",
        },
    )


@app.post("/v1/descriptions/generate-csv-compare")
def generate_descriptions_csv_compare(file: UploadFile = File(...)) -> dict:
    """Generate two CSV outputs from two models and return a quality comparison."""
    fieldnames, rows_list, row_tuples = _parse_uploaded_csv(file)

    generation_a = generator.generate_column_descriptions_for_rows_with_model(row_tuples, OLLAMA_MODEL)
    generation_b = generator.generate_column_descriptions_for_rows_with_model(row_tuples, OLLAMA_COMPARE_MODEL)

    csv_a = _build_output_csv(fieldnames, rows_list, generation_a.descriptions)
    csv_b = _build_output_csv(fieldnames, rows_list, generation_b.descriptions)
    comparison = _compare_models(
        generation_a.model_version,
        generation_b.model_version,
        generation_a.descriptions,
        generation_b.descriptions,
    )

    return {
        "model_a": {
            "provider": generation_a.provider,
            "model": generation_a.model_version,
            "used_llm": generation_a.used_llm,
            "filename": f"descriptions_{generation_a.model_version.replace(':', '_')}.csv",
            "csv": csv_a,
        },
        "model_b": {
            "provider": generation_b.provider,
            "model": generation_b.model_version,
            "used_llm": generation_b.used_llm,
            "filename": f"descriptions_{generation_b.model_version.replace(':', '_')}.csv",
            "csv": csv_b,
        },
        "comparison": comparison,
    }


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
    configured = (
        f"Model A: <code>{OLLAMA_MODEL}</code> | Model B: <code>{OLLAMA_COMPARE_MODEL}</code> (local Ollama, then OpenAI <code>{OPENAI_MODEL}</code> fallback)"
        if PREFER_LOCAL_LLM
        else f"Model A: <code>{OLLAMA_MODEL}</code> | Model B: <code>{OLLAMA_COMPARE_MODEL}</code> (OpenAI <code>{OPENAI_MODEL}</code> preferred)"
    )
    html = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Banking Data Dictionary AI</title>
  <style>
    :root{
      --bg:#f2f6f3;
      --ink:#162028;
      --card:#ffffff;
      --accent:#0f766e;
      --muted:#506070;
      --line:#d2d9dc;
      --ok:#0d7a43;
      --err:#b42318;
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      font-family:"Avenir Next","Segoe UI",sans-serif;
      color:var(--ink);
      background:
        radial-gradient(circle at 15% 10%, #d7efe7 0%, transparent 32%),
        radial-gradient(circle at 85% 82%, #f3e8d2 0%, transparent 36%),
        var(--bg);
      min-height:100vh;
      display:flex;
      align-items:center;
      justify-content:center;
      padding:20px;
    }
    .card{
      width:100%;
      max-width:700px;
      background:var(--card);
      border:1px solid var(--line);
      border-radius:18px;
      padding:22px;
      box-shadow:0 16px 38px rgba(11,19,26,.08);
    }
    h1{margin:0 0 6px;font-size:30px}
    p{margin:0;color:var(--muted);line-height:1.5}
    .tip{margin-top:8px;font-size:13px}
    input[type=file]{
      width:100%;
      margin-top:18px;
      border:1px dashed #9ab4b0;
      background:#f8fcfa;
      border-radius:12px;
      padding:14px;
    }
    button,a.btn{
      background:var(--accent);
      color:#fff;
      border:none;
      border-radius:12px;
      padding:11px 16px;
      font-weight:600;
      cursor:pointer;
      text-decoration:none;
      display:inline-block;
      margin-top:14px;
    }
    button[disabled]{opacity:.55;cursor:not-allowed}
    .actions{display:flex;gap:10px;flex-wrap:wrap}
    .status{margin-top:14px;font-weight:600}
    .status.ok{color:var(--ok)}
    .status.err{color:var(--err)}
    .meta{
      margin-top:12px;
      font-size:14px;
      color:var(--ink);
      background:#edf7f6;
      border:1px solid #cbe4df;
      border-radius:10px;
      padding:10px;
    }
    .preview-wrap{margin-top:12px;overflow:auto}
    table{width:100%;border-collapse:collapse;font-size:13px}
    th,td{border:1px solid #dce4e6;padding:8px;text-align:left;vertical-align:top}
    th{background:#f6f8f9}
    .hide{display:none}
  </style>
</head>
<body>
  <div class="card">
    <h1>Two-Model CSV Comparison</h1>
    <p>Upload one CSV (<code>table_name</code>, <code>column_name</code>). The app will generate two output CSV files from two LLMs, compare quality, and recommend the better one.</p>
    <p class="tip">Single action: upload, process, compare, download both files.</p>
    <div id="llmConfigured" class="meta"><strong>Configured Models:</strong> __CONFIGURED_LLM__</div>
    <input type="file" id="csvFile" accept=".csv" />
    <div class="actions">
      <button id="processBtn" onclick="runCompareCsv()">Process & Compare</button>
      <a id="downloadLinkA" class="btn hide" download="descriptions_model_a.csv">Download CSV (Model A)</a>
      <a id="downloadLinkB" class="btn hide" download="descriptions_model_b.csv">Download CSV (Model B)</a>
    </div>
    <div id="status" class="status"></div>
    <div id="llmInfo" class="meta">Last run: not processed yet</div>
    <div id="comparisonInfo" class="meta hide"></div>
    <div class="preview-wrap hide" id="previewWrapA">
      <p><strong>Model A Output Preview</strong></p>
      <table>
        <thead id="previewHeadA"></thead>
        <tbody id="previewBodyA"></tbody>
      </table>
    </div>
    <div class="preview-wrap hide" id="previewWrapB">
      <p><strong>Model B Output Preview</strong></p>
      <table>
        <thead id="previewHeadB"></thead>
        <tbody id="previewBodyB"></tbody>
      </table>
    </div>
  </div>
  <script>
    const statusEl = document.getElementById("status");
    const processBtn = document.getElementById("processBtn");
    const downloadLinkA = document.getElementById("downloadLinkA");
    const downloadLinkB = document.getElementById("downloadLinkB");
    const llmInfo = document.getElementById("llmInfo");
    const comparisonInfo = document.getElementById("comparisonInfo");
    const previewWrapA = document.getElementById("previewWrapA");
    const previewHeadA = document.getElementById("previewHeadA");
    const previewBodyA = document.getElementById("previewBodyA");
    const previewWrapB = document.getElementById("previewWrapB");
    const previewHeadB = document.getElementById("previewHeadB");
    const previewBodyB = document.getElementById("previewBodyB");

    function setStatus(text, type){
      statusEl.textContent = text;
      statusEl.className = "status " + (type || "");
    }

    function parseCsv(csvText){
      const rows = [];
      let row = [];
      let cell = "";
      let inQuotes = false;
      for(let i = 0; i < csvText.length; i++){
        const ch = csvText[i];
        const next = csvText[i + 1];
        if(ch === '"'){
          if(inQuotes && next === '"'){
            cell += '"';
            i += 1;
          } else {
            inQuotes = !inQuotes;
          }
          continue;
        }
        if(ch === "," && !inQuotes){
          row.push(cell);
          cell = "";
          continue;
        }
        if((ch === "\\n" || ch === "\\r") && !inQuotes){
          if(ch === "\\r" && next === "\\n"){ i += 1; }
          row.push(cell);
          cell = "";
          if(row.length > 1 || (row.length === 1 && row[0] !== "")){
            rows.push(row);
          }
          row = [];
          continue;
        }
        cell += ch;
      }
      if(cell.length || row.length){
        row.push(cell);
        rows.push(row);
      }
      if(rows.length < 2){ return {headers: [], rows: []}; }
      return {headers: rows[0], rows: rows.slice(1)};
    }

    function renderPreview(csvText, headEl, bodyEl, wrapEl){
      const parsed = parseCsv(csvText);
      headEl.innerHTML = "";
      bodyEl.innerHTML = "";
      if(!parsed.headers.length){ wrapEl.classList.add("hide"); return; }
      const headRow = document.createElement("tr");
      parsed.headers.forEach((h) => {
        const th = document.createElement("th");
        th.textContent = h;
        headRow.appendChild(th);
      });
      headEl.appendChild(headRow);
      parsed.rows.slice(0, 12).forEach((r) => {
        const tr = document.createElement("tr");
        parsed.headers.forEach((_, i) => {
          const td = document.createElement("td");
          td.textContent = r[i] || "";
          tr.appendChild(td);
        });
        bodyEl.appendChild(tr);
      });
      wrapEl.classList.remove("hide");
    }

    async function runCompareCsv(){
      const input = document.getElementById("csvFile");
      if(!input.files || !input.files[0]){
        setStatus("Please select a CSV file first.", "err");
        return;
      }
      processBtn.disabled = true;
      setStatus("Generating descriptions with both models...", "");
      downloadLinkA.classList.add("hide");
      downloadLinkB.classList.add("hide");
      comparisonInfo.classList.add("hide");
      previewWrapA.classList.add("hide");
      previewWrapB.classList.add("hide");
      const form = new FormData();
      form.append("file", input.files[0]);
      const res = await fetch("/v1/descriptions/generate-csv-compare", { method: "POST", body: form });
      const text = await res.text();
      if(!res.ok){
        setStatus("Processing failed. Please confirm CSV headers: table_name,column_name", "err");
        try {
          const err = JSON.parse(text);
          llmInfo.textContent = String(err.detail || text);
        } catch(_) {
          llmInfo.textContent = text;
        }
        processBtn.disabled = false;
        return;
      }
      const data = JSON.parse(text);
      const a = data.model_a;
      const b = data.model_b;
      const c = data.comparison;
      setStatus("Done. Two files generated and compared.", "ok");
      llmInfo.textContent = "Model A: " + a.provider + " / " + a.model + " (LLM used: " + a.used_llm + ") | Model B: " + b.provider + " / " + b.model + " (LLM used: " + b.used_llm + ")";
      comparisonInfo.classList.remove("hide");
      comparisonInfo.textContent =
        "Winner: " + c.winner_model +
        " | Score A: " + c.model_a_metrics.score +
        " | Score B: " + c.model_b_metrics.score +
        " | " + c.reason;

      renderPreview(a.csv, previewHeadA, previewBodyA, previewWrapA);
      renderPreview(b.csv, previewHeadB, previewBodyB, previewWrapB);

      const blobA = new Blob([a.csv], { type: "text/csv" });
      const blobB = new Blob([b.csv], { type: "text/csv" });
      downloadLinkA.href = URL.createObjectURL(blobA);
      downloadLinkA.download = a.filename || "descriptions_model_a.csv";
      downloadLinkA.classList.remove("hide");
      downloadLinkB.href = URL.createObjectURL(blobB);
      downloadLinkB.download = b.filename || "descriptions_model_b.csv";
      downloadLinkB.classList.remove("hide");
      processBtn.disabled = false;
    }
  </script>
</body>
</html>
"""
    return html.replace("__CONFIGURED_LLM__", configured)
