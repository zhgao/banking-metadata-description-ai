from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_generate_csv_adds_column_description() -> None:
    csv_content = "table_name,column_name\ncustomer_account,acct_open_dt\n"
    response = client.post(
        "/v1/descriptions/generate-csv",
        files={"file": ("columns.csv", csv_content.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.headers.get("x-llm-provider")
    assert response.headers.get("x-llm-model")
    assert response.headers.get("x-llm-used") in {"true", "false"}
    text = response.text
    assert "table_name" in text and "column_name" in text and "column_description" in text
    lines = text.strip().split("\n")
    assert len(lines) >= 2
    header = lines[0]
    assert "column_description" in header


def test_generate_validate_review_flow() -> None:
    samples_res = client.get("/v1/demo/samples")
    assert samples_res.status_code == 200
    assert any(s["name"] == "customer_account" for s in samples_res.json())

    sample_res = client.get("/v1/demo/sample", params={"name": "customer_account"})
    assert sample_res.status_code == 200
    generate_payload = sample_res.json()

    gen_res = client.post("/v1/descriptions/generate", json=generate_payload)
    assert gen_res.status_code == 200
    gen_data = gen_res.json()
    assert "columns" in gen_data

    validate_res = client.post(
        "/v1/descriptions/validate",
        json={"table_name": "customer_account", "generated_payload": gen_data},
    )
    assert validate_res.status_code == 200
    assert "valid" in validate_res.json()

    review_res = client.post(
        "/v1/reviews/submit",
        json={
            "table_name": "customer_account",
            "reviewer": "judge@hackathon.dev",
            "decisions": [{"column_name": "acct_open_dt", "action": "approved"}],
            "generated_columns": gen_data["columns"],
        },
    )
    assert review_res.status_code == 200
    assert review_res.json()["status"] == "saved"

    csv_res = client.get("/v1/dictionary/export.csv")
    assert csv_res.status_code == 200
    assert "column_name" in csv_res.text
