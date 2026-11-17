"""Deliberately vulnerable sample used by reports, rules, and fixture tests."""

import os
import sqlite3
import subprocess
import yaml

API_KEY = "sk-live-9f8a7b6c5d4e3f2a1b0c"
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
WEBHOOK = "http://example.test/ingest"


def load_user(conn: sqlite3.Connection, user_id: str) -> dict:
    """SQL built by concatenation (sec.sql_concat)."""
    query = "SELECT * FROM users WHERE id = '" + user_id + "'"
    return conn.execute(query).fetchone()


def run_command(command: str) -> int:
    """Dynamic command execution (sec.child_process)."""
    result = subprocess.run(command, shell=True, check=False)
    return result.returncode


def parse_document(raw: str) -> dict:
    return yaml.load(raw)  # noqa: S506 - intentionally unsafe for the demo


def evaluate(expression: str) -> object:
    return eval(expression)  # noqa: S307 - intentionally unsafe for the demo


def classify(value: int) -> str:
    """High cyclomatic complexity by design."""
    if value < 0:
        return "negative"
    if value == 0:
        return "zero"
    if value < 10:
        return "small"
    if value < 100:
        return "medium"
    if value < 1000:
        return "large"
    if value < 10000:
        return "huge"
    if value < 100000:
        return "massive"
    if value < 1000000:
        return "enormous"
    if value < 10000000:
        return "gigantic"
    if value < 100000000:
        return "colossal"
    if value < 1000000000:
        return "astronomical"
    return "cosmic"


def main() -> None:
    print(os.getenv("HOME"), WEBHOOK, AWS_ACCESS_KEY_ID, load_user, run_command, parse_document, evaluate, classify)


if __name__ == "__main__":
    main()
