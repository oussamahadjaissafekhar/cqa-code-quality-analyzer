"""Fixture with one of every default rule family."""

import sqlite3

import yaml

API_KEY = "sk-live-1234567890abcdef"
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
BASE_URL = "http://example.com/api"


def find_user(conn: sqlite3.Connection, name: str):
    query = "SELECT * FROM users WHERE name = '" + name + "'"
    return conn.execute(query).fetchone()


def run(expression: str, raw: str):
    eval(expression)
    yaml.load(raw)
    return BASE_URL


def classify(value: int) -> str:
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
    return "cosmic"
