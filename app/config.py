from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REVIEWS_PATH = BASE_DIR / "reviews.jsonl"
DICTIONARY_PATH = BASE_DIR / "dictionary.jsonl"
BANKING_TERMS_PATH = DATA_DIR / "banking_terms.yaml"
DEMO_SAMPLES_PATH = DATA_DIR / "demo_samples.json"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MAX_SAMPLE_VALUES = int(os.getenv("MAX_SAMPLE_VALUES", "5"))
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
