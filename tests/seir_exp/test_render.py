"""Golden-ish tests for SEIR renderers."""

from __future__ import annotations

from seir.render import ARMS, render
from seir.types import SpanContext

LOGIN = SpanContext(
    file="auth.py",
    start_line=1,
    end_line=12,
    symbol="login",
    source=(
        "def login(email, password):\n"
        "    ok = bcrypt.compare(password, user.password)\n"
        "    if not ok:\n"
        "        logger.warning('bad login')\n"
        "        return None\n"
        "    token = generateJWT(user.id)\n"
        "    session.token = token\n"
        "    return token\n"
    ),
    node_kind="function",
)


def test_arms_listed():
    assert "baseline" in ARMS
    assert "mix_rels" in ARMS
    assert len(ARMS) == 6


def test_mix_rels_keeps_calls_under_cap():
    text = render("mix_rels", LOGIN, max_chars=512)
    assert len(text) <= 512
    assert "bcrypt" in text.lower() or "Calls:" in text or "generateJWT" in text


def test_ast_tree_has_function_and_calls():
    text = render("ast_tree", LOGIN, max_chars=512)
    assert "login" in text
    assert "Call" in text or "bcrypt" in text
    assert len(text) <= 512


def test_rels_lists_calls_and_writes():
    text = render("rels", LOGIN)
    assert "Function: login" in text
    assert "bcrypt.compare" in text or "Calls:" in text
    assert "generateJWT" in text
    assert "session.token" in text or "Writes:" in text


def test_semantic_auth_purpose():
    text = render("semantic", LOGIN)
    assert "Purpose: Authentication" in text
    assert "email" in text and "password" in text


def test_importance_drops_logger_keeps_bcrypt():
    text = render("importance", LOGIN)
    assert "bcrypt" in text.lower() or "generateJWT" in text
    assert "logger.warning" not in text


def test_baseline_deterministic_length():
    a = render("baseline", LOGIN, max_chars=512)
    b = render("baseline", LOGIN, max_chars=512)
    assert a == b
    assert len(a) <= 512
