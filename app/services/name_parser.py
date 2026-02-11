from __future__ import annotations

import re

ABBREVIATIONS = {
    "acct": "account",
    "acc": "account",
    "txn": "transaction",
    "dt": "date",
    "amt": "amount",
    "num": "number",
    "no": "number",
    "cust": "customer",
    "bal": "balance",
    "kyc": "know your customer",
    "aml": "anti money laundering",
    "cd": "code",
    "id": "identifier",
}


def split_identifier(name: str) -> list[str]:
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()
    parts = [p for p in snake.split("_") if p]
    return [ABBREVIATIONS.get(p, p) for p in parts]


def humanize_identifier(name: str) -> str:
    return " ".join(split_identifier(name))
