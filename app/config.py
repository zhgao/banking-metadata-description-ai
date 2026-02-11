from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None  # type: ignore[assignment]

BASE_DIR = Path(__file__).resolve().parent.parent
if load_dotenv:
    load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
REVIEWS_PATH = BASE_DIR / "reviews.jsonl"
DICTIONARY_PATH = BASE_DIR / "dictionary.jsonl"
BANKING_TERMS_PATH = DATA_DIR / "banking_terms.yaml"
DEMO_SAMPLES_PATH = DATA_DIR / "demo_samples.json"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")
OLLAMA_COMPARE_MODEL = os.getenv("OLLAMA_COMPARE_MODEL", "qwen3-coder:30b")
PREFER_LOCAL_LLM = os.getenv("PREFER_LOCAL_LLM", "true").lower() in {"1", "true", "yes", "on"}
MAX_SAMPLE_VALUES = int(os.getenv("MAX_SAMPLE_VALUES", "5"))
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
