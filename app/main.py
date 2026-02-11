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
        generation = generator.generate_column_descriptions_for_rows(row_tuples)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    out_headers = [f for f in fieldnames if f != "column_description"] + ["column_description"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=out_headers, extrasaction="ignore")
    writer.writeheader()
    for row, col_desc in zip(rows_list, generation.descriptions, strict=True):
        row["column_description"] = col_desc
        writer.writerow(row)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=descriptions.csv",
            "X-LLM-Provider": generation.provider,
            "X-LLM-Model": generation.model_version,
            "X-LLM-Used": "true" if generation.used_llm else "false",
        },
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
    <h1>CSV Description Generator</h1>
    <p>Upload one CSV with headers <code>table_name</code> and <code>column_name</code>. The system will process it and produce a downloadable CSV with <code>column_description</code>.</p>
    <p class="tip">No other setup is required on this page.</p>
    <input type="file" id="csvFile" accept=".csv" />
    <div class="actions">
      <button id="processBtn" onclick="runGenerateCsv()">Process CSV</button>
      <a id="downloadLink" class="btn hide" download="descriptions.csv">Download CSV</a>
    </div>
    <div id="status" class="status"></div>
    <div id="llmInfo" class="meta hide"></div>
    <div class="preview-wrap hide" id="previewWrap">
      <table>
        <thead id="previewHead"></thead>
        <tbody id="previewBody"></tbody>
      </table>
    </div>
  </div>
  <script>
    const statusEl = document.getElementById("status");
    const processBtn = document.getElementById("processBtn");
    const downloadLink = document.getElementById("downloadLink");
    const llmInfo = document.getElementById("llmInfo");
    const previewWrap = document.getElementById("previewWrap");
    const previewHead = document.getElementById("previewHead");
    const previewBody = document.getElementById("previewBody");

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

    function renderPreview(csvText){
      const parsed = parseCsv(csvText);
      previewHead.innerHTML = "";
      previewBody.innerHTML = "";
      if(!parsed.headers.length){ previewWrap.classList.add("hide"); return; }
      const headRow = document.createElement("tr");
      parsed.headers.forEach((h) => {
        const th = document.createElement("th");
        th.textContent = h;
        headRow.appendChild(th);
      });
      previewHead.appendChild(headRow);
      parsed.rows.slice(0, 12).forEach((r) => {
        const tr = document.createElement("tr");
        parsed.headers.forEach((_, i) => {
          const td = document.createElement("td");
          td.textContent = r[i] || "";
          tr.appendChild(td);
        });
        previewBody.appendChild(tr);
      });
      previewWrap.classList.remove("hide");
    }

    async function runGenerateCsv(){
      const input = document.getElementById("csvFile");
      if(!input.files || !input.files[0]){
        setStatus("Please select a CSV file first.", "err");
        return;
      }
      processBtn.disabled = true;
      setStatus("Processing your file...", "");
      downloadLink.classList.add("hide");
      llmInfo.classList.add("hide");
      previewWrap.classList.add("hide");
      const form = new FormData();
      form.append("file", input.files[0]);
      const res = await fetch("/v1/descriptions/generate-csv", { method: "POST", body: form });
      const text = await res.text();
      if(!res.ok){
        setStatus("Processing failed. Please confirm CSV headers: table_name,column_name", "err");
        llmInfo.classList.remove("hide");
        try {
          const err = JSON.parse(text);
          llmInfo.textContent = String(err.detail || text);
        } catch(_) {
          llmInfo.textContent = text;
        }
        processBtn.disabled = false;
        return;
      }
      const provider = res.headers.get("x-llm-provider") || "unknown";
      const model = res.headers.get("x-llm-model") || "unknown";
      const usedLlm = res.headers.get("x-llm-used") || "false";
      setStatus("Done. Your file is ready to download.", "ok");
      llmInfo.classList.remove("hide");
      llmInfo.textContent = "Generator: " + provider + " | Model: " + model + " | LLM used: " + usedLlm;
      renderPreview(text);
      const blob = new Blob([text], { type: "text/csv" });
      downloadLink.href = URL.createObjectURL(blob);
      downloadLink.classList.remove("hide");
      processBtn.disabled = false;
    }
  </script>
</body>
</html>
"""
