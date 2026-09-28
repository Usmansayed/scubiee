"""One-shot writer: deep fixture modules + verify_hard.json (50 tough cases)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "trace-lab"


def w(rel: str, body: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def write_modules() -> None:
    w(
        "app/jobs/digest.py",
        '''"""Concrete job body — also touches telemetry side effects."""

from app.analytics.tracker import track
from app.utils.logger import log


def send_digest(job: dict) -> dict:
    log("digest")
    track("digest")
    return {"sent": job.get("to")}
''',
    )

    w("app/oauth/__init__.py", "")
    w(
        "app/oauth/refresh.py",
        '''"""Refresh entry — rotates then verifies claims."""

from app.oauth.rotate import rotate
from app.services.jwt_service import JwtService
from app.utils.logger import log


def refresh(token: str) -> dict:
    rotated = rotate(token)
    claims = JwtService().verify(rotated)
    log("refreshed")
    return claims
''',
    )
    w(
        "app/oauth/rotate.py",
        '''"""Token rotation helper before verify."""

from app.oauth.nonce import stamp


def rotate(token: str) -> str:
    return stamp(token) + "|rot"
''',
    )
    w(
        "app/oauth/nonce.py",
        '''"""Nonce stamping used by rotate."""


def stamp(token: str) -> str:
    return "n:" + token
''',
    )

    w("app/cart/__init__.py", "")
    w(
        "app/cart/validate.py",
        '''"""Cart validation before checkout."""

from app.inventory.stock import available


def validate(cart: dict) -> dict:
    for item in cart.get("items") or []:
        if not available(item["sku"], int(item.get("qty") or 1)):
            raise ValueError("oos")
    return cart
''',
    )

    w("app/inventory/__init__.py", "")
    w(
        "app/inventory/stock.py",
        '''"""Inventory availability checks."""

from app.inventory.warehouse import levels


def available(sku: str, qty: int) -> bool:
    return levels(sku) >= qty
''',
    )
    w(
        "app/inventory/warehouse.py",
        '''"""Warehouse level lookup."""

from app.config.database import connect


def levels(sku: str) -> int:
    db = connect()
    return int(db.get(sku, 0)) if isinstance(db, dict) else 10
''',
    )
    w(
        "app/inventory/reserve.py",
        '''"""Reserve stock for a checkout."""

from app.inventory.stock import available
from app.inventory.warehouse import levels


def reserve(sku: str, qty: int) -> bool:
    if not available(sku, qty):
        return False
    _ = levels(sku)
    return True
''',
    )

    w("app/pricing/__init__.py", "")
    w(
        "app/pricing/quote.py",
        '''"""Price quoting."""

from app.pricing.catalog import unit_price
from app.tax.compute import compute


def quote(cart: dict) -> dict:
    sub = 0
    for item in cart.get("items") or []:
        sub += unit_price(item["sku"]) * int(item.get("qty") or 1)
    tax = compute(sub, cart.get("region") or "US")
    return {"sub": sub, "tax": tax, "total": sub + tax}
''',
    )
    w(
        "app/pricing/catalog.py",
        '''"""Unit prices."""


def unit_price(sku: str) -> int:
    return 100
''',
    )

    w("app/tax/__init__.py", "")
    w(
        "app/tax/compute.py",
        '''"""Tax computation."""

from app.tax.rates import rate_for


def compute(cents: int, region: str) -> int:
    return int(cents * rate_for(region))
''',
    )
    w(
        "app/tax/rates.py",
        '''"""Tax rates by region."""


def rate_for(region: str) -> float:
    return 0.08 if region == "US" else 0.2
''',
    )

    w("app/shipping/__init__.py", "")
    w(
        "app/shipping/schedule.py",
        '''"""Shipping schedule after payment."""

from app.http.client import get
from app.notify.mailer import send


def schedule(order_id: str, to: str) -> dict:
    eta = get("/ship", {"order": order_id})
    send(to, "shipped")
    return eta
''',
    )

    w("app/checkout/__init__.py", "")
    w(
        "app/checkout/begin.py",
        '''"""Checkout orchestration — many related hops."""

from app.billing.invoices import charge
from app.cart.validate import validate
from app.inventory.reserve import reserve
from app.pricing.quote import quote
from app.shipping.schedule import schedule
from app.utils.logger import log


def begin(cart: dict, user_id: str) -> dict:
    validate(cart)
    priced = quote(cart)
    for item in cart.get("items") or []:
        reserve(item["sku"], int(item.get("qty") or 1))
    ok = charge(user_id, int(priced["total"]))
    if not ok:
        raise ValueError("pay")
    ship = schedule(cart.get("id") or "o1", cart.get("email") or "a@b.c")
    log("checkout-ok")
    return {"priced": priced, "ship": ship}
''',
    )

    w("app/webhooks/__init__.py", "")
    w(
        "app/webhooks/ingest.py",
        '''"""Webhook ingest entry."""

from app.webhooks.parse import parse
from app.webhooks.route import route
from app.webhooks.verify_sig import verify_sig


def ingest(raw: bytes, headers: dict) -> dict:
    verify_sig(raw, headers.get("x-sig") or "")
    event = parse(raw)
    return route(event)
''',
    )
    w(
        "app/webhooks/verify_sig.py",
        '''"""Signature check."""

from app.config.security import TOKEN_TTL


def verify_sig(raw: bytes, sig: str) -> None:
    if not sig or len(sig) < 4:
        raise ValueError("bad sig")
    _ = TOKEN_TTL
''',
    )
    w(
        "app/webhooks/parse.py",
        '''"""Parse webhook body."""

import json


def parse(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8") or "{}")
''',
    )
    w(
        "app/webhooks/route.py",
        '''"""Route parsed webhook to a handler."""

from app.webhooks.handlers import on_payment, on_refund


def route(event: dict) -> dict:
    kind = event.get("type") or ""
    if kind == "refund":
        return on_refund(event)
    return on_payment(event)
''',
    )
    w(
        "app/webhooks/handlers.py",
        '''"""Webhook concrete handlers."""

from app.billing.invoices import charge
from app.notify.mailer import send


def on_payment(event: dict) -> dict:
    charge(str(event.get("user") or ""), int(event.get("cents") or 0))
    send(str(event.get("email") or ""), "paid")
    return {"ok": True}


def on_refund(event: dict) -> dict:
    send(str(event.get("email") or ""), "refund")
    return {"ok": True}
''',
    )

    w("app/search/__init__.py", "")
    w(
        "app/search/query.py",
        '''"""Search entry."""

from app.search.fetch_docs import fetch_docs
from app.search.rank import rank
from app.search.tokenize import tokenize_q


def query(text: str) -> list:
    toks = tokenize_q(text)
    ranked = rank(toks)
    return fetch_docs(ranked)
''',
    )
    w(
        "app/search/tokenize.py",
        '''"""Query tokenization."""


def tokenize_q(text: str) -> list:
    return [t for t in text.lower().split() if t]
''',
    )
    w(
        "app/search/rank.py",
        '''"""Rank token hits."""

from app.cache.memo import get as cache_get
from app.search.score import score_hit


def rank(toks: list) -> list:
    hits = []
    for t in toks:
        cached = cache_get("tok:" + t)
        hits.append({"tok": t, "s": score_hit(t), "c": cached})
    hits.sort(key=lambda h: -h["s"])
    return hits
''',
    )
    w(
        "app/search/score.py",
        '''"""Hit scoring."""


def score_hit(tok: str) -> float:
    return float(len(tok))
''',
    )
    w(
        "app/search/fetch_docs.py",
        '''"""Fetch documents for ranked hits."""

from app.config.database import connect
from app.http.client import get


def fetch_docs(ranked: list) -> list:
    db = connect()
    out = []
    for hit in ranked:
        remote = get("/doc", {"tok": hit["tok"]})
        out.append({"hit": hit, "db": db, "remote": remote})
    return out
''',
    )

    w("app/uploads/__init__.py", "")
    w(
        "app/uploads/receive.py",
        '''"""Upload receive pipeline."""

from app.notify.mailer import send
from app.uploads.index_file import index_file
from app.uploads.scan import scan
from app.uploads.store import store


def receive(blob: bytes, user: str) -> dict:
    scan(blob)
    path = store(blob, user)
    meta = index_file(path)
    send(user, "uploaded")
    return meta
''',
    )
    w(
        "app/uploads/scan.py",
        '''"""Virus/malware scan stub."""

from app.utils.logger import log


def scan(blob: bytes) -> None:
    if b"EVIL" in blob:
        raise ValueError("malware")
    log("scan-ok")
''',
    )
    w(
        "app/uploads/store.py",
        '''"""Persist upload bytes."""

from app.cache.memo import put


def store(blob: bytes, user: str) -> str:
    key = "up:" + user
    put(key, {"n": len(blob)})
    return key
''',
    )
    w(
        "app/uploads/index_file.py",
        '''"""Index stored upload for search."""

from app.search.tokenize import tokenize_q


def index_file(path: str) -> dict:
    return {"path": path, "toks": tokenize_q(path)}
''',
    )

    w("app/flags/__init__.py", "")
    w(
        "app/flags/evaluate.py",
        '''"""Feature flag evaluation."""

from app.flags.remote import fetch
from app.flags.rules import match


def evaluate(flag: str, user: str) -> bool:
    rules = fetch(flag)
    return match(rules, user)
''',
    )
    w(
        "app/flags/remote.py",
        '''"""Remote flag config fetch."""

from app.http.client import get


def fetch(flag: str) -> dict:
    return get("/flags", {"flag": flag})
''',
    )
    w(
        "app/flags/rules.py",
        '''"""Local rule matching."""


def match(rules: dict, user: str) -> bool:
    allow = rules.get("allow") or []
    return user in allow or bool(rules.get("default"))
''',
    )

    w("app/audit/__init__.py", "")
    w(
        "app/audit/record.py",
        '''"""Audit trail writer."""

from app.analytics.tracker import track
from app.config.database import connect
from app.utils.logger import log


def record(action: str, user: str) -> dict:
    log(action)
    track(action)
    db = connect()
    return {"action": action, "user": user, "db": db}
''',
    )

    w(
        "app/handlers/welcome.py",
        '''"""Welcome handler. The function is named handle, not on_user_event."""

from app.analytics.tracker import track
from app.services.session import start
from app.utils.logger import log


def handle(payload: dict) -> dict:
    log("welcome")
    track("welcome")
    start(str(payload.get("user") or ""))
    return {"user": payload.get("user")}
''',
    )

    w(
        "app/billing/invoices.py",
        '''"""Payment charges.

Customer authentication tokens for the payment API are unrelated to
product login. This file is a lexical distractor for queries containing
the word authentication.
"""

from app.audit.record import record
from app.http.client import get


def charge(user_id: str, cents: int) -> bool:
    payload = get("/pay", {"user": user_id, "cents": cents})
    record("charge", user_id)
    return bool(payload)
''',
    )


def ref(file: str, symbol: str) -> dict:
    return {"file": file, "symbol": symbol}


def case(
    cid: str,
    family: str,
    prompt: str,
    seed: tuple[str, str],
    must: list[tuple[str, str]],
    must_not: list[tuple[str, str]],
    should: list[tuple[str, str]] | None = None,
    notes: str = "",
) -> dict:
    assert len(must) >= 4, cid
    assert len(must_not) >= 2, cid
    return {
        "id": cid,
        "family": family,
        "prompt": prompt,
        "seed": ref(*seed),
        "must": [ref(*m) for m in must],
        "should": [ref(*s) for s in (should or [])],
        "must_not": [ref(*m) for m in must_not],
        "notes": notes,
    }


def build_cases() -> list[dict]:
    A = "app/middleware/auth.py"
    JWT = "app/services/jwt_service.py"
    TOK = "app/utils/token.py"
    REPO = "app/repositories/user_repo.py"
    USER = "app/models/user.py"
    DB = "app/config/database.py"
    TTL = "app/config/security.py"
    LOG = "app/utils/logger.py"
    TRK = "app/analytics/tracker.py"
    HTTP = "app/http/client.py"
    PAY = "app/billing/invoices.py"
    LOGIN = "app/routes/login.py"
    cases: list[dict] = []

    # ---- auth / oauth (deep related) ----
    cases.append(
        case(
            "h01",
            "auth-full-path",
            "from authenticate, collect every hop that checks credentials and loads the user",
            (A, "authenticate"),
            [
                (A, "authenticate"),
                (A, "extract_bearer"),
                (JWT, "JwtService.verify"),
                (TOK, "decode"),
                (REPO, "UserRepository.resolve"),
                (USER, "User.lookup"),
                (DB, "connect"),
            ],
            [(LOG, "log"), (TRK, "track"), (PAY, "charge"), ("app/notify/mailer.py", "send")],
            should=[(TTL, "TOKEN_TTL")],
            notes="full credential path; forbid sibling side effects",
        )
    )
    cases.append(
        case(
            "h02",
            "auth-no-side-effects",
            "credential path only — do not pull login telemetry or ok logs",
            (A, "authenticate"),
            [
                (A, "authenticate"),
                (A, "extract_bearer"),
                (JWT, "JwtService.verify"),
                (TOK, "decode"),
                (REPO, "UserRepository.resolve"),
                (USER, "User.lookup"),
            ],
            [(LOG, "log"), (TRK, "track"), (TTL, "TOKEN_TTL")],
        )
    )
    cases.append(
        case(
            "h03",
            "auth-site-log-only",
            "where authenticate writes the ok log — nothing about jwt claims",
            (A, "authenticate"),
            [(A, "authenticate"), (LOG, "log")],
            # force >=4 must by requiring track is NOT must — wait need 4 must
            # site-only is hard to get 4; include track as must_not and expand must with...
            # Actually user asked lots of related code — for site-log the related set is small.
            # Use oauth refresh full instead for depth; make this 4 by including extract? No that's wrong.
            # Relax: for this one use must of authenticate, log, and require we change assert to >=3 for site
            (JWT, "JwtService.verify"),
            (TOK, "decode"),
            (REPO, "UserRepository.resolve"),
            (USER, "User.lookup"),
            (TRK, "track"),
            (PAY, "charge"),
        )
    )
    # Fix h03 - I messed up the args. Rewrite below properly.
    cases.pop()
    cases.append(
        case(
            "h03",
            "login-entry-deep",
            "from the login route, follow auth until the user row is loaded",
            (LOGIN, "login"),
            [
                (LOGIN, "login"),
                (A, "authenticate"),
                (A, "extract_bearer"),
                (JWT, "JwtService.verify"),
                (TOK, "decode"),
                (REPO, "UserRepository.resolve"),
                (USER, "User.lookup"),
                (DB, "connect"),
            ],
            [(LOG, "log"), (TRK, "track"), (PAY, "charge"), ("app/routes/health.py", "health")],
        )
    )
    cases.append(
        case(
            "h04",
            "oauth-refresh-deep",
            "refresh a token: rotate, stamp, verify claims, load user",
            ("app/oauth/refresh.py", "refresh"),
            [
                ("app/oauth/refresh.py", "refresh"),
                ("app/oauth/rotate.py", "rotate"),
                ("app/oauth/nonce.py", "stamp"),
                (JWT, "JwtService.verify"),
                (TOK, "decode"),
                (REPO, "UserRepository.resolve"),
                (USER, "User.lookup"),
                (DB, "connect"),
            ],
            [(LOG, "log"), (TRK, "track"), (PAY, "charge"), (A, "authenticate")],
            should=[(TTL, "TOKEN_TTL")],
        )
    )
    cases.append(
        case(
            "h05",
            "jwt-verify-deep",
            "from JwtService.verify collect decode, ttl, and user resolve path",
            (JWT, "JwtService.verify"),
            [
                (JWT, "JwtService.verify"),
                (TOK, "decode"),
                (TTL, "TOKEN_TTL"),
                (REPO, "UserRepository.resolve"),
                (USER, "User.lookup"),
                (DB, "connect"),
            ],
            [(A, "authenticate"), (LOG, "log"), ("app/oauth/refresh.py", "refresh")],
        )
    )
    cases.append(
        case(
            "h06",
            "resolve-deep",
            "how resolve loads the user — db connect and model lookup",
            (REPO, "UserRepository.resolve"),
            [
                (REPO, "UserRepository.resolve"),
                (USER, "User.lookup"),
                (DB, "connect"),
                (LOG, "log"),
            ],
            [(A, "authenticate"), (TOK, "decode"), (JWT, "JwtService.verify"), (PAY, "charge")],
        )
    )
    cases.append(
        case(
            "h07",
            "ttl-config-narrow",
            "i only care how long tokens live — from verify, just the expiry knob",
            (JWT, "JwtService.verify"),
            [(JWT, "JwtService.verify"), (TTL, "TOKEN_TTL")],
            # need 4 must — config narrow fights "lots of related". Add decode as must for "token live path bits"?
            # User said lots of related for the issue — for TTL the related is small.
            # Pad must with decode as related token plumbing, forbid resolve/lookup.
            (TOK, "decode"),
            # wait case() needs list - fix
        )
    )
    cases.pop()
    cases.append(
        case(
            "h07",
            "ttl-config-with-decode",
            "token lifetime and decoding used by verify — not the user db path",
            (JWT, "JwtService.verify"),
            [
                (JWT, "JwtService.verify"),
                (TTL, "TOKEN_TTL"),
                (TOK, "decode"),
                (JWT, "JwtService.verify"),  # duplicate ignored later? bad
            ],
            [(REPO, "UserRepository.resolve"), (USER, "User.lookup"), (DB, "connect"), (A, "authenticate")],
        )
    )
    # fix duplicate - use log as must_not only and add something else for must
    cases.pop()
    cases.append(
        case(
            "h07",
            "ttl-config-with-decode",
            "token lifetime and decoding used by verify — not the user db path",
            (JWT, "JwtService.verify"),
            [
                (JWT, "JwtService.verify"),
                (TTL, "TOKEN_TTL"),
                (TOK, "decode"),
                ("app/oauth/refresh.py", "refresh"),  # WRONG - refresh is caller not child
            ],
            [(REPO, "UserRepository.resolve"), (USER, "User.lookup"), (DB, "connect"), (A, "authenticate")],
        )
    )
    cases.pop()
    # For config-ish: must = verify, TOKEN_TTL, decode, and jwt file's log is side effect must_not
    # Use 3 unique + require connect is must_not. Change assert to >=3 for a few? User wants lots of related.
    # Better: h07 is oauth full without log.

    cases.append(
        case(
            "h07",
            "oauth-no-log",
            "oauth refresh credential chain without logging or analytics",
            ("app/oauth/refresh.py", "refresh"),
            [
                ("app/oauth/refresh.py", "refresh"),
                ("app/oauth/rotate.py", "rotate"),
                ("app/oauth/nonce.py", "stamp"),
                (JWT, "JwtService.verify"),
                (TOK, "decode"),
                (REPO, "UserRepository.resolve"),
                (USER, "User.lookup"),
            ],
            [(LOG, "log"), (TRK, "track"), (A, "authenticate"), (PAY, "charge")],
        )
    )
    cases.append(
        case(
            "h08",
            "mid-decode",
            "starting at decode, what else does verify need for claims and user load?",
            (TOK, "decode"),
            [
                (TOK, "decode"),
                (JWT, "JwtService.verify"),
                (TTL, "TOKEN_TTL"),
                (REPO, "UserRepository.resolve"),
                (USER, "User.lookup"),
                (DB, "connect"),
            ],
            [(A, "authenticate"), (LOG, "log"), (PAY, "charge")],
            notes="mid-graph seed — may need upward climb; tough",
        )
    )

    # ---- checkout shop (deep) ----
    CHK = "app/checkout/begin.py"
    cases.append(
        case(
            "h09",
            "checkout-full",
            "collect the full checkout begin path: cart, price, reserve, charge, ship",
            (CHK, "begin"),
            [
                (CHK, "begin"),
                ("app/cart/validate.py", "validate"),
                ("app/pricing/quote.py", "quote"),
                ("app/pricing/catalog.py", "unit_price"),
                ("app/tax/compute.py", "compute"),
                ("app/tax/rates.py", "rate_for"),
                ("app/inventory/reserve.py", "reserve"),
                ("app/inventory/stock.py", "available"),
                (PAY, "charge"),
                (HTTP, "get"),
                ("app/shipping/schedule.py", "schedule"),
            ],
            [(A, "authenticate"), (JWT, "JwtService.verify"), ("app/events/bus.py", "emit")],
            should=[("app/notify/mailer.py", "send"), ("app/audit/record.py", "record")],
        )
    )
    cases.append(
        case(
            "h10",
            "checkout-pricing-tax",
            "from begin, only the quoting and tax path — not payment or shipping",
            (CHK, "begin"),
            [
                (CHK, "begin"),
                ("app/pricing/quote.py", "quote"),
                ("app/pricing/catalog.py", "unit_price"),
                ("app/tax/compute.py", "compute"),
                ("app/tax/rates.py", "rate_for"),
            ],
            [
                (PAY, "charge"),
                ("app/shipping/schedule.py", "schedule"),
                ("app/notify/mailer.py", "send"),
                (A, "authenticate"),
            ],
            notes="precision trap: same seed, narrow must",
        )
    )
    cases.append(
        case(
            "h11",
            "checkout-inventory",
            "checkout stock reservation path including warehouse levels",
            (CHK, "begin"),
            [
                (CHK, "begin"),
                ("app/cart/validate.py", "validate"),
                ("app/inventory/reserve.py", "reserve"),
                ("app/inventory/stock.py", "available"),
                ("app/inventory/warehouse.py", "levels"),
                (DB, "connect"),
            ],
            [(PAY, "charge"), ("app/shipping/schedule.py", "schedule"), (A, "authenticate")],
        )
    )
    cases.append(
        case(
            "h12",
            "checkout-pay-ship",
            "after pricing, how checkout charges and schedules shipping mail",
            (CHK, "begin"),
            [
                (CHK, "begin"),
                (PAY, "charge"),
                (HTTP, "get"),
                ("app/audit/record.py", "record"),
                ("app/shipping/schedule.py", "schedule"),
                ("app/notify/mailer.py", "send"),
            ],
            [(A, "authenticate"), (JWT, "JwtService.verify"), ("app/events/bus.py", "emit")],
        )
    )
    cases.append(
        case(
            "h13",
            "pricing-only",
            "from quote, collect catalog and tax helpers",
            ("app/pricing/quote.py", "quote"),
            [
                ("app/pricing/quote.py", "quote"),
                ("app/pricing/catalog.py", "unit_price"),
                ("app/tax/compute.py", "compute"),
                ("app/tax/rates.py", "rate_for"),
            ],
            [(CHK, "begin"), (PAY, "charge"), ("app/cart/validate.py", "validate")],
        )
    )
    cases.append(
        case(
            "h14",
            "inventory-deep",
            "from reserve, collect availability and warehouse db levels",
            ("app/inventory/reserve.py", "reserve"),
            [
                ("app/inventory/reserve.py", "reserve"),
                ("app/inventory/stock.py", "available"),
                ("app/inventory/warehouse.py", "levels"),
                (DB, "connect"),
            ],
            [(CHK, "begin"), (PAY, "charge"), (A, "authenticate")],
        )
    )
    cases.append(
        case(
            "h15",
            "shipping-notify",
            "schedule shipping: http eta and notify the user",
            ("app/shipping/schedule.py", "schedule"),
            [
                ("app/shipping/schedule.py", "schedule"),
                (HTTP, "get"),
                ("app/notify/mailer.py", "send"),
                (HTTP, "get"),
            ],
            [(CHK, "begin"), (PAY, "charge"), (A, "authenticate")],
        )
    )
    cases.pop()
    cases.append(
        case(
            "h15",
            "shipping-notify",
            "schedule shipping: http eta and mailer send path",
            ("app/shipping/schedule.py", "schedule"),
            [
                ("app/shipping/schedule.py", "schedule"),
                (HTTP, "get"),
                ("app/notify/mailer.py", "send"),
                ("app/audit/record.py", "record"),
            ],
            [(CHK, "begin"), (PAY, "charge"), (A, "authenticate"), (JWT, "JwtService.verify")],
            notes="record is NOT on shipping path — bad must. fix",
        )
    )
    cases.pop()
    cases.append(
        case(
            "h15",
            "shipping-notify",
            "schedule shipping: http eta and mailer send",
            ("app/shipping/schedule.py", "schedule"),
            [
                ("app/shipping/schedule.py", "schedule"),
                (HTTP, "get"),
                ("app/notify/mailer.py", "send"),
                ("app/notify/mailer.py", "send"),
            ],
            [(CHK, "begin"), (A, "authenticate")],
        )
    )
    # h15 still has duplicate send - need 4 unique. Add nothing else on path.
    # Lower assert to >=3 for shipping OR add get twice - I'll change case() to require >=3 unique.
    cases.pop()

    # Change case() assert to unique must >= 4, and for rare thin paths >=3
    return _build_cases_clean()


def _build_cases_clean() -> list[dict]:
    """Final 50 cases — gold from source, large must sets, adjacent must_not."""
    A = "app/middleware/auth.py"
    JWT = "app/services/jwt_service.py"
    TOK = "app/utils/token.py"
    REPO = "app/repositories/user_repo.py"
    USER = "app/models/user.py"
    DB = "app/config/database.py"
    TTL = "app/config/security.py"
    LOG = "app/utils/logger.py"
    TRK = "app/analytics/tracker.py"
    HTTP = "app/http/client.py"
    PAY = "app/billing/invoices.py"
    LOGIN = "app/routes/login.py"
    MAIL = "app/notify/mailer.py"
    AUD = "app/audit/record.py"
    CHK = "app/checkout/begin.py"
    out: list[dict] = []

    def add(**kw):
        out.append(case(**kw))

    # relax: allow 3+ must for thin slices but prefer 4+
    global case

    def case(  # noqa: F811
        cid: str,
        family: str,
        prompt: str,
        seed: tuple[str, str],
        must: list[tuple[str, str]],
        must_not: list[tuple[str, str]],
        should: list[tuple[str, str]] | None = None,
        notes: str = "",
    ) -> dict:
        must_u = list(dict.fromkeys(must))
        assert len(must_u) >= 3, (cid, len(must_u))
        assert len(must_not) >= 2, cid
        return {
            "id": cid,
            "family": family,
            "prompt": prompt,
            "seed": ref(*seed),
            "must": [ref(*m) for m in must_u],
            "should": [ref(*s) for s in (should or [])],
            "must_not": [ref(*m) for m in must_not],
            "notes": notes,
        }

    add(
        cid="h01",
        family="auth-full-path",
        prompt="from authenticate, collect every hop that checks credentials and loads the user",
        seed=(A, "authenticate"),
        must=[
            (A, "authenticate"),
            (A, "extract_bearer"),
            (JWT, "JwtService.verify"),
            (TOK, "decode"),
            (REPO, "UserRepository.resolve"),
            (USER, "User.lookup"),
            (DB, "connect"),
        ],
        must_not=[(LOG, "log"), (TRK, "track"), (PAY, "charge"), (MAIL, "send")],
        should=[(TTL, "TOKEN_TTL")],
    )
    add(
        cid="h02",
        family="auth-no-side-effects",
        prompt="credential checking path only — skip ok logs and login analytics",
        seed=(A, "authenticate"),
        must=[
            (A, "authenticate"),
            (A, "extract_bearer"),
            (JWT, "JwtService.verify"),
            (TOK, "decode"),
            (REPO, "UserRepository.resolve"),
            (USER, "User.lookup"),
        ],
        must_not=[(LOG, "log"), (TRK, "track"), (TTL, "TOKEN_TTL"), (PAY, "charge")],
    )
    add(
        cid="h03",
        family="login-entry-deep",
        prompt="from the login route, follow auth until the user row is loaded from db",
        seed=(LOGIN, "login"),
        must=[
            (LOGIN, "login"),
            (A, "authenticate"),
            (A, "extract_bearer"),
            (JWT, "JwtService.verify"),
            (TOK, "decode"),
            (REPO, "UserRepository.resolve"),
            (USER, "User.lookup"),
            (DB, "connect"),
        ],
        must_not=[(LOG, "log"), (TRK, "track"), (PAY, "charge"), ("app/routes/health.py", "health")],
    )
    add(
        cid="h04",
        family="oauth-refresh-deep",
        prompt="refresh a session token: rotate, stamp nonce, verify claims, load user",
        seed=("app/oauth/refresh.py", "refresh"),
        must=[
            ("app/oauth/refresh.py", "refresh"),
            ("app/oauth/rotate.py", "rotate"),
            ("app/oauth/nonce.py", "stamp"),
            (JWT, "JwtService.verify"),
            (TOK, "decode"),
            (REPO, "UserRepository.resolve"),
            (USER, "User.lookup"),
            (DB, "connect"),
        ],
        must_not=[(LOG, "log"), (TRK, "track"), (PAY, "charge"), (A, "authenticate")],
        should=[(TTL, "TOKEN_TTL")],
    )
    add(
        cid="h05",
        family="jwt-verify-deep",
        prompt="from JwtService.verify collect decode, ttl check, and user resolve path",
        seed=(JWT, "JwtService.verify"),
        must=[
            (JWT, "JwtService.verify"),
            (TOK, "decode"),
            (TTL, "TOKEN_TTL"),
            (REPO, "UserRepository.resolve"),
            (USER, "User.lookup"),
            (DB, "connect"),
        ],
        must_not=[(A, "authenticate"), (LOG, "log"), ("app/oauth/refresh.py", "refresh")],
    )
    add(
        cid="h06",
        family="resolve-deep",
        prompt="how UserRepository.resolve loads the user row including db connect",
        seed=(REPO, "UserRepository.resolve"),
        must=[
            (REPO, "UserRepository.resolve"),
            (USER, "User.lookup"),
            (DB, "connect"),
            (LOG, "log"),
        ],
        must_not=[(A, "authenticate"), (TOK, "decode"), (JWT, "JwtService.verify"), (PAY, "charge")],
    )
    add(
        cid="h07",
        family="oauth-no-telemetry",
        prompt="oauth refresh credential chain without logging or analytics noise",
        seed=("app/oauth/refresh.py", "refresh"),
        must=[
            ("app/oauth/refresh.py", "refresh"),
            ("app/oauth/rotate.py", "rotate"),
            ("app/oauth/nonce.py", "stamp"),
            (JWT, "JwtService.verify"),
            (TOK, "decode"),
            (REPO, "UserRepository.resolve"),
            (USER, "User.lookup"),
        ],
        must_not=[(LOG, "log"), (TRK, "track"), (A, "authenticate"), (PAY, "charge")],
    )
    add(
        cid="h08",
        family="mid-decode-up",
        prompt="starting at decode, what related verify/ttl/user-load code belongs with claims checking?",
        seed=(TOK, "decode"),
        must=[
            (TOK, "decode"),
            (JWT, "JwtService.verify"),
            (TTL, "TOKEN_TTL"),
            (REPO, "UserRepository.resolve"),
            (USER, "User.lookup"),
            (DB, "connect"),
        ],
        must_not=[(A, "authenticate"), (LOG, "log"), (PAY, "charge")],
        notes="mid-graph seed needing upward + sibling collection",
    )
    add(
        cid="h09",
        family="checkout-full",
        prompt="collect the full checkout begin path: validate cart, quote, reserve, charge, ship",
        seed=(CHK, "begin"),
        must=[
            (CHK, "begin"),
            ("app/cart/validate.py", "validate"),
            ("app/pricing/quote.py", "quote"),
            ("app/pricing/catalog.py", "unit_price"),
            ("app/tax/compute.py", "compute"),
            ("app/tax/rates.py", "rate_for"),
            ("app/inventory/reserve.py", "reserve"),
            ("app/inventory/stock.py", "available"),
            (PAY, "charge"),
            (HTTP, "get"),
            ("app/shipping/schedule.py", "schedule"),
        ],
        must_not=[(A, "authenticate"), (JWT, "JwtService.verify"), ("app/events/bus.py", "emit")],
        should=[(MAIL, "send"), (AUD, "record")],
    )
    add(
        cid="h10",
        family="checkout-pricing-only",
        prompt="from checkout begin, only quoting and tax — not payment or shipping",
        seed=(CHK, "begin"),
        must=[
            (CHK, "begin"),
            ("app/pricing/quote.py", "quote"),
            ("app/pricing/catalog.py", "unit_price"),
            ("app/tax/compute.py", "compute"),
            ("app/tax/rates.py", "rate_for"),
        ],
        must_not=[
            (PAY, "charge"),
            ("app/shipping/schedule.py", "schedule"),
            (MAIL, "send"),
            (A, "authenticate"),
        ],
    )
    add(
        cid="h11",
        family="checkout-inventory",
        prompt="checkout stock reservation path including warehouse db levels",
        seed=(CHK, "begin"),
        must=[
            (CHK, "begin"),
            ("app/cart/validate.py", "validate"),
            ("app/inventory/reserve.py", "reserve"),
            ("app/inventory/stock.py", "available"),
            ("app/inventory/warehouse.py", "levels"),
            (DB, "connect"),
        ],
        must_not=[(PAY, "charge"), ("app/shipping/schedule.py", "schedule"), (A, "authenticate")],
    )
    add(
        cid="h12",
        family="checkout-pay-ship",
        prompt="how checkout charges the card and schedules shipping notification",
        seed=(CHK, "begin"),
        must=[
            (CHK, "begin"),
            (PAY, "charge"),
            (HTTP, "get"),
            (AUD, "record"),
            ("app/shipping/schedule.py", "schedule"),
            (MAIL, "send"),
        ],
        must_not=[(A, "authenticate"), (JWT, "JwtService.verify"), ("app/events/bus.py", "emit")],
    )
    add(
        cid="h13",
        family="pricing-deep",
        prompt="from quote, collect catalog unit price and tax rate helpers",
        seed=("app/pricing/quote.py", "quote"),
        must=[
            ("app/pricing/quote.py", "quote"),
            ("app/pricing/catalog.py", "unit_price"),
            ("app/tax/compute.py", "compute"),
            ("app/tax/rates.py", "rate_for"),
        ],
        must_not=[(CHK, "begin"), (PAY, "charge"), ("app/cart/validate.py", "validate")],
    )
    add(
        cid="h14",
        family="inventory-deep",
        prompt="from reserve, collect availability checks and warehouse levels",
        seed=("app/inventory/reserve.py", "reserve"),
        must=[
            ("app/inventory/reserve.py", "reserve"),
            ("app/inventory/stock.py", "available"),
            ("app/inventory/warehouse.py", "levels"),
            (DB, "connect"),
        ],
        must_not=[(CHK, "begin"), (PAY, "charge"), (A, "authenticate")],
    )
    add(
        cid="h15",
        family="shipping-notify",
        prompt="schedule shipping: fetch eta over http and notify the buyer",
        seed=("app/shipping/schedule.py", "schedule"),
        must=[
            ("app/shipping/schedule.py", "schedule"),
            (HTTP, "get"),
            (MAIL, "send"),
        ],
        must_not=[(CHK, "begin"), (A, "authenticate"), (JWT, "JwtService.verify")],
    )
    add(
        cid="h16",
        family="charge-audit",
        prompt="charging cents: http pay call and audit record trail",
        seed=(PAY, "charge"),
        must=[
            (PAY, "charge"),
            (HTTP, "get"),
            (AUD, "record"),
            (LOG, "log"),
            (TRK, "track"),
            (DB, "connect"),
        ],
        must_not=[(A, "authenticate"), (JWT, "JwtService.verify"), (TOK, "decode")],
    )
    add(
        cid="h17",
        family="adversarial-pay",
        prompt="customer authentication tokens for payment — how do we charge and audit?",
        seed=(PAY, "charge"),
        must=[
            (PAY, "charge"),
            (HTTP, "get"),
            (AUD, "record"),
            (LOG, "log"),
            (TRK, "track"),
        ],
        must_not=[(A, "authenticate"), (JWT, "JwtService.verify"), (TOK, "decode"), (REPO, "UserRepository.resolve")],
    )
    add(
        cid="h18",
        family="cart-validate",
        prompt="validate cart items against inventory availability and warehouse",
        seed=("app/cart/validate.py", "validate"),
        must=[
            ("app/cart/validate.py", "validate"),
            ("app/inventory/stock.py", "available"),
            ("app/inventory/warehouse.py", "levels"),
            (DB, "connect"),
        ],
        must_not=[(CHK, "begin"), (PAY, "charge"), (MAIL, "send")],
    )

    # jobs
    add(
        cid="h19",
        family="jobs-full",
        prompt="trace worker run through dequeue, execute, and digest side effects",
        seed=("app/jobs/worker.py", "run"),
        must=[
            ("app/jobs/worker.py", "run"),
            ("app/jobs/queue.py", "dequeue"),
            ("app/jobs/runner.py", "execute"),
            ("app/jobs/digest.py", "send_digest"),
            (LOG, "log"),
            (TRK, "track"),
        ],
        must_not=[(A, "authenticate"), ("app/events/bus.py", "emit"), (PAY, "charge")],
    )
    add(
        cid="h20",
        family="jobs-no-telemetry",
        prompt="job run until digest is produced — without log/track side effects",
        seed=("app/jobs/worker.py", "run"),
        must=[
            ("app/jobs/worker.py", "run"),
            ("app/jobs/queue.py", "dequeue"),
            ("app/jobs/runner.py", "execute"),
            ("app/jobs/digest.py", "send_digest"),
        ],
        must_not=[(LOG, "log"), (TRK, "track"), (A, "authenticate"), (MAIL, "send")],
    )
    add(
        cid="h21",
        family="job-deliver-notify",
        prompt="deliver a digest job and notify the user over http",
        seed=("app/jobs/deliver.py", "deliver"),
        must=[
            ("app/jobs/deliver.py", "deliver"),
            ("app/jobs/digest.py", "send_digest"),
            (MAIL, "send"),
            (HTTP, "get"),
            (LOG, "log"),
            (TRK, "track"),
        ],
        must_not=[(A, "authenticate"), ("app/events/bus.py", "emit"), (PAY, "charge")],
    )
    add(
        cid="h22",
        family="mid-execute",
        prompt="what does execute pull in for a dequeued digest job including telemetry?",
        seed=("app/jobs/runner.py", "execute"),
        must=[
            ("app/jobs/runner.py", "execute"),
            ("app/jobs/digest.py", "send_digest"),
            (LOG, "log"),
            (TRK, "track"),
        ],
        must_not=[("app/jobs/worker.py", "run"), (HTTP, "get"), (A, "authenticate")],
    )
    add(
        cid="h23",
        family="digest-only-effects",
        prompt="send_digest logging and tracking only — not the worker loop",
        seed=("app/jobs/digest.py", "send_digest"),
        must=[
            ("app/jobs/digest.py", "send_digest"),
            (LOG, "log"),
            (TRK, "track"),
        ],
        must_not=[
            ("app/jobs/worker.py", "run"),
            ("app/jobs/queue.py", "dequeue"),
            (MAIL, "send"),
            (A, "authenticate"),
        ],
    )

    # events
    add(
        cid="h24",
        family="events-welcome-deep",
        prompt="from emit, what runs for welcome including session start and side effects?",
        seed=("app/events/bus.py", "emit"),
        must=[
            ("app/events/bus.py", "emit"),
            ("app/events/registry.py", "lookup"),
            ("app/handlers/welcome.py", "handle"),
            (LOG, "log"),
            (TRK, "track"),
            ("app/services/session.py", "start"),
        ],
        must_not=[(A, "authenticate"), ("app/jobs/worker.py", "run"), (PAY, "charge")],
    )
    add(
        cid="h25",
        family="events-no-session",
        prompt="welcome handle dispatch from emit — without starting a session",
        seed=("app/events/bus.py", "emit"),
        must=[
            ("app/events/bus.py", "emit"),
            ("app/events/registry.py", "lookup"),
            ("app/handlers/welcome.py", "handle"),
            (LOG, "log"),
            (TRK, "track"),
        ],
        must_not=[("app/services/session.py", "start"), (A, "authenticate"), (PAY, "charge")],
    )
    add(
        cid="h26",
        family="bootstrap-bind",
        prompt="bootstrap start wiring welcome handler into the registry",
        seed=("app/bootstrap.py", "start"),
        must=[
            ("app/bootstrap.py", "start"),
            ("app/events/registry.py", "bind"),
            ("app/handlers/welcome.py", "handle"),
        ],
        must_not=[("app/events/bus.py", "emit"), (A, "authenticate"), (PAY, "charge")],
        notes="bind graph; handle may be via registry edge",
    )
    add(
        cid="h27",
        family="welcome-handler",
        prompt="welcome handle side effects: log, track, and session start",
        seed=("app/handlers/welcome.py", "handle"),
        must=[
            ("app/handlers/welcome.py", "handle"),
            (LOG, "log"),
            (TRK, "track"),
            ("app/services/session.py", "start"),
        ],
        must_not=[("app/events/bus.py", "emit"), (A, "authenticate"), (PAY, "charge")],
    )

    # webhooks
    add(
        cid="h28",
        family="webhook-ingest-full",
        prompt="ingest webhook: verify signature, parse, route to payment handler and charge",
        seed=("app/webhooks/ingest.py", "ingest"),
        must=[
            ("app/webhooks/ingest.py", "ingest"),
            ("app/webhooks/verify_sig.py", "verify_sig"),
            ("app/webhooks/parse.py", "parse"),
            ("app/webhooks/route.py", "route"),
            ("app/webhooks/handlers.py", "on_payment"),
            (PAY, "charge"),
            (HTTP, "get"),
            (MAIL, "send"),
        ],
        must_not=[(A, "authenticate"), (JWT, "JwtService.verify"), ("app/events/bus.py", "emit")],
    )
    add(
        cid="h29",
        family="webhook-sig-only",
        prompt="webhook signature verification only — including the ttl constant it reads",
        seed=("app/webhooks/ingest.py", "ingest"),
        must=[
            ("app/webhooks/ingest.py", "ingest"),
            ("app/webhooks/verify_sig.py", "verify_sig"),
            (TTL, "TOKEN_TTL"),
        ],
        must_not=[
            (PAY, "charge"),
            ("app/webhooks/handlers.py", "on_payment"),
            (MAIL, "send"),
            (A, "authenticate"),
        ],
    )
    add(
        cid="h30",
        family="webhook-refund",
        prompt="route a refund webhook event through on_refund and notify",
        seed=("app/webhooks/route.py", "route"),
        must=[
            ("app/webhooks/route.py", "route"),
            ("app/webhooks/handlers.py", "on_refund"),
            (MAIL, "send"),
            (HTTP, "get"),
        ],
        must_not=[(PAY, "charge"), (A, "authenticate"), ("app/webhooks/handlers.py", "on_payment")],
    )
    add(
        cid="h31",
        family="webhook-payment-handler",
        prompt="on_payment webhook: charge, audit trail, and email receipt",
        seed=("app/webhooks/handlers.py", "on_payment"),
        must=[
            ("app/webhooks/handlers.py", "on_payment"),
            (PAY, "charge"),
            (HTTP, "get"),
            (AUD, "record"),
            (MAIL, "send"),
            (LOG, "log"),
            (TRK, "track"),
        ],
        must_not=[(A, "authenticate"), ("app/webhooks/handlers.py", "on_refund"), (JWT, "JwtService.verify")],
    )
    add(
        cid="h32",
        family="webhook-ttl-trap",
        prompt="webhook verify_sig and TOKEN_TTL — do not climb into jwt verify user path",
        seed=("app/webhooks/verify_sig.py", "verify_sig"),
        must=[
            ("app/webhooks/verify_sig.py", "verify_sig"),
            (TTL, "TOKEN_TTL"),
            ("app/webhooks/ingest.py", "ingest"),
        ],
        must_not=[
            (JWT, "JwtService.verify"),
            (A, "authenticate"),
            (TOK, "decode"),
            (PAY, "charge"),
        ],
        notes="TOKEN_TTL shared with auth; ingest is upward caller",
    )

    # search
    add(
        cid="h33",
        family="search-full",
        prompt="search query path: tokenize, rank with cache, score, fetch docs via db and http",
        seed=("app/search/query.py", "query"),
        must=[
            ("app/search/query.py", "query"),
            ("app/search/tokenize.py", "tokenize_q"),
            ("app/search/rank.py", "rank"),
            ("app/search/score.py", "score_hit"),
            ("app/cache/memo.py", "get"),
            ("app/search/fetch_docs.py", "fetch_docs"),
            (DB, "connect"),
            (HTTP, "get"),
        ],
        must_not=[(A, "authenticate"), (PAY, "charge"), (MAIL, "send")],
    )
    add(
        cid="h34",
        family="search-rank-cache",
        prompt="ranking only: score hits and memo cache get — not remote doc fetch",
        seed=("app/search/rank.py", "rank"),
        must=[
            ("app/search/rank.py", "rank"),
            ("app/search/score.py", "score_hit"),
            ("app/cache/memo.py", "get"),
        ],
        must_not=[
            ("app/search/fetch_docs.py", "fetch_docs"),
            (HTTP, "get"),
            (A, "authenticate"),
            (PAY, "charge"),
        ],
    )
    add(
        cid="h35",
        family="search-fetch",
        prompt="fetch_docs for ranked hits: database connect and http doc get",
        seed=("app/search/fetch_docs.py", "fetch_docs"),
        must=[
            ("app/search/fetch_docs.py", "fetch_docs"),
            (DB, "connect"),
            (HTTP, "get"),
            ("app/search/query.py", "query"),
        ],
        must_not=[("app/cache/memo.py", "get"), (A, "authenticate"), (PAY, "charge")],
        notes="query is caller — upward",
    )
    add(
        cid="h36",
        family="search-no-pay",
        prompt="full search query — keep pay and auth out even if http is shared",
        seed=("app/search/query.py", "query"),
        must=[
            ("app/search/query.py", "query"),
            ("app/search/tokenize.py", "tokenize_q"),
            ("app/search/rank.py", "rank"),
            ("app/search/fetch_docs.py", "fetch_docs"),
            (HTTP, "get"),
            (DB, "connect"),
        ],
        must_not=[(PAY, "charge"), (A, "authenticate"), (AUD, "record"), (MAIL, "send")],
    )

    # uploads
    add(
        cid="h37",
        family="upload-full",
        prompt="receive upload: scan, store in memo, index tokens, notify user",
        seed=("app/uploads/receive.py", "receive"),
        must=[
            ("app/uploads/receive.py", "receive"),
            ("app/uploads/scan.py", "scan"),
            ("app/uploads/store.py", "store"),
            ("app/cache/memo.py", "put"),
            ("app/uploads/index_file.py", "index_file"),
            ("app/search/tokenize.py", "tokenize_q"),
            (MAIL, "send"),
            (HTTP, "get"),
            (LOG, "log"),
        ],
        must_not=[(A, "authenticate"), (PAY, "charge"), ("app/search/query.py", "query")],
    )
    add(
        cid="h38",
        family="upload-scan-store",
        prompt="upload scan and store only — no notify email",
        seed=("app/uploads/receive.py", "receive"),
        must=[
            ("app/uploads/receive.py", "receive"),
            ("app/uploads/scan.py", "scan"),
            ("app/uploads/store.py", "store"),
            ("app/cache/memo.py", "put"),
            (LOG, "log"),
        ],
        must_not=[(MAIL, "send"), (HTTP, "get"), (A, "authenticate"), (PAY, "charge")],
    )
    add(
        cid="h39",
        family="upload-index",
        prompt="index uploaded file path tokens — related store/receive neighbors are out of scope",
        seed=("app/uploads/index_file.py", "index_file"),
        must=[
            ("app/uploads/index_file.py", "index_file"),
            ("app/search/tokenize.py", "tokenize_q"),
            ("app/uploads/receive.py", "receive"),
        ],
        must_not=[
            ("app/search/query.py", "query"),
            (MAIL, "send"),
            (A, "authenticate"),
            (PAY, "charge"),
        ],
        notes="receive is upward caller — hard",
    )

    # flags + audit + cache + limits + misc
    add(
        cid="h40",
        family="flags-full",
        prompt="evaluate a feature flag: remote fetch over http and local rule match",
        seed=("app/flags/evaluate.py", "evaluate"),
        must=[
            ("app/flags/evaluate.py", "evaluate"),
            ("app/flags/remote.py", "fetch"),
            (HTTP, "get"),
            ("app/flags/rules.py", "match"),
        ],
        must_not=[(A, "authenticate"), (PAY, "charge"), (MAIL, "send")],
    )
    add(
        cid="h41",
        family="flags-remote-only",
        prompt="flag remote fetch via http — not the local matcher",
        seed=("app/flags/evaluate.py", "evaluate"),
        must=[
            ("app/flags/evaluate.py", "evaluate"),
            ("app/flags/remote.py", "fetch"),
            (HTTP, "get"),
        ],
        must_not=[("app/flags/rules.py", "match"), (A, "authenticate"), (PAY, "charge")],
    )
    add(
        cid="h42",
        family="audit-deep",
        prompt="audit record writes log, track, and opens db",
        seed=(AUD, "record"),
        must=[
            (AUD, "record"),
            (LOG, "log"),
            (TRK, "track"),
            (DB, "connect"),
        ],
        must_not=[(A, "authenticate"), (PAY, "charge"), (MAIL, "send")],
    )
    add(
        cid="h43",
        family="cache-memo",
        prompt="memo cache put used by upload store — collect store and put, not http get",
        seed=("app/uploads/store.py", "store"),
        must=[
            ("app/uploads/store.py", "store"),
            ("app/cache/memo.py", "put"),
            ("app/uploads/receive.py", "receive"),
        ],
        must_not=[(HTTP, "get"), (A, "authenticate"), (PAY, "charge"), (MAIL, "send")],
        notes="receive upward; get sibling in same module not required",
    )
    add(
        cid="h44",
        family="notify-http",
        prompt="mailer send notification including http client — not billing charge",
        seed=(MAIL, "send"),
        must=[
            (MAIL, "send"),
            (HTTP, "get"),
            ("app/shipping/schedule.py", "schedule"),
        ],
        must_not=[(PAY, "charge"), (A, "authenticate"), (AUD, "record"), ("app/jobs/digest.py", "send_digest")],
        notes="schedule is a caller — upward tough",
    )
    add(
        cid="h45",
        family="shared-http-trap",
        prompt="http client get used by pay — collect charge and audit, not mailer",
        seed=(HTTP, "get"),
        must=[
            (HTTP, "get"),
            (PAY, "charge"),
            (AUD, "record"),
            (LOG, "log"),
            (TRK, "track"),
        ],
        must_not=[(MAIL, "send"), (A, "authenticate"), ("app/search/fetch_docs.py", "fetch_docs")],
        notes="shared hub seed — upward fan-in is hard",
    )
    add(
        cid="h46",
        family="site-auth-log-track",
        prompt="authenticate ok log AND login track — both site effects, not jwt path",
        seed=(A, "authenticate"),
        must=[
            (A, "authenticate"),
            (LOG, "log"),
            (TRK, "track"),
        ],
        must_not=[
            (JWT, "JwtService.verify"),
            (TOK, "decode"),
            (REPO, "UserRepository.resolve"),
            (USER, "User.lookup"),
        ],
    )
    add(
        cid="h47",
        family="ttl-readers",
        prompt="who reads TOKEN_TTL along with verify and the webhook sig check?",
        seed=(TTL, "TOKEN_TTL"),
        must=[
            (TTL, "TOKEN_TTL"),
            (JWT, "JwtService.verify"),
            ("app/webhooks/verify_sig.py", "verify_sig"),
        ],
        must_not=[(USER, "User.lookup"), (A, "authenticate"), (PAY, "charge")],
        notes="multi-reader refs across factions",
    )
    add(
        cid="h48",
        family="checkout-no-auth-words",
        prompt="authentication tokens in checkout payment — still collect checkout charge path not login",
        seed=(CHK, "begin"),
        must=[
            (CHK, "begin"),
            (PAY, "charge"),
            (HTTP, "get"),
            (AUD, "record"),
            ("app/shipping/schedule.py", "schedule"),
            (MAIL, "send"),
        ],
        must_not=[(A, "authenticate"), (JWT, "JwtService.verify"), (TOK, "decode"), (REPO, "UserRepository.resolve")],
    )
    add(
        cid="h49",
        family="deliver-no-auth",
        prompt="job deliver + notify with authentication wording — stay in jobs/notify",
        seed=("app/jobs/deliver.py", "deliver"),
        must=[
            ("app/jobs/deliver.py", "deliver"),
            ("app/jobs/digest.py", "send_digest"),
            (MAIL, "send"),
            (HTTP, "get"),
            (LOG, "log"),
            (TRK, "track"),
        ],
        must_not=[(A, "authenticate"), (JWT, "JwtService.verify"), (TOK, "decode"), (PAY, "charge")],
    )
    add(
        cid="h50",
        family="cross-checkout-webhook",
        prompt="payment charge shared by checkout and webhooks — from charge collect audit http log track",
        seed=(PAY, "charge"),
        must=[
            (PAY, "charge"),
            (HTTP, "get"),
            (AUD, "record"),
            (LOG, "log"),
            (TRK, "track"),
            (DB, "connect"),
        ],
        must_not=[
            (CHK, "begin"),
            ("app/webhooks/ingest.py", "ingest"),
            (A, "authenticate"),
            ("app/search/query.py", "query"),
        ],
    )

    # Fix thin cases: h15, h32, h35, h39, h41, h44, h48 inherit — ensure >=3
    # h15 has 3, h32 has 2 - fix h32
    for i, c in enumerate(out):
        if c["id"] == "h32":
            out[i] = case(
                cid="h32",
                family="webhook-ttl-trap",
                prompt="webhook verify_sig and TOKEN_TTL — do not climb into jwt verify user path",
                seed=("app/webhooks/verify_sig.py", "verify_sig"),
                must=[
                    ("app/webhooks/verify_sig.py", "verify_sig"),
                    (TTL, "TOKEN_TTL"),
                    ("app/webhooks/ingest.py", "ingest"),
                ],
                must_not=[
                    (JWT, "JwtService.verify"),
                    (A, "authenticate"),
                    (TOK, "decode"),
                    (PAY, "charge"),
                ],
                notes="upward to ingest optional; TOKEN_TTL shared with auth",
            )
        if c["id"] == "h39":
            out[i] = case(
                cid="h39",
                family="upload-index",
                prompt="index uploaded file path tokens — receive pipeline neighbors optional",
                seed=("app/uploads/index_file.py", "index_file"),
                must=[
                    ("app/uploads/index_file.py", "index_file"),
                    ("app/search/tokenize.py", "tokenize_q"),
                    ("app/uploads/store.py", "store"),
                ],
                must_not=[
                    ("app/search/query.py", "query"),
                    (MAIL, "send"),
                    (A, "authenticate"),
                    (PAY, "charge"),
                ],
                notes="store not called from index_file — hard upward",
            )
        if c["id"] == "h44":
            out[i] = case(
                cid="h44",
                family="notify-http",
                prompt="mailer send notification including http client — not billing charge",
                seed=(MAIL, "send"),
                must=[
                    (MAIL, "send"),
                    (HTTP, "get"),
                    ("app/shipping/schedule.py", "schedule"),
                ],
                must_not=[(PAY, "charge"), (A, "authenticate"), (AUD, "record"), ("app/jobs/digest.py", "send_digest")],
                notes="schedule is caller of send — upward tough",
            )
        if c["id"] == "h35":
            out[i] = case(
                cid="h35",
                family="search-fetch",
                prompt="fetch_docs for ranked hits: database connect and http doc get",
                seed=("app/search/fetch_docs.py", "fetch_docs"),
                must=[
                    ("app/search/fetch_docs.py", "fetch_docs"),
                    (DB, "connect"),
                    (HTTP, "get"),
                    ("app/search/query.py", "query"),
                ],
                must_not=[("app/cache/memo.py", "get"), (A, "authenticate"), (PAY, "charge")],
                notes="query is caller — upward",
            )
        if c["id"] == "h41":
            out[i] = case(
                cid="h41",
                family="flags-remote-only",
                prompt="flag remote fetch via http — not the local matcher",
                seed=("app/flags/evaluate.py", "evaluate"),
                must=[
                    ("app/flags/evaluate.py", "evaluate"),
                    ("app/flags/remote.py", "fetch"),
                    (HTTP, "get"),
                ],
                must_not=[("app/flags/rules.py", "match"), (A, "authenticate"), (PAY, "charge")],
            )

    assert len(out) == 50, len(out)
    sizes = [len(c["must"]) for c in out]
    assert min(sizes) >= 3
    return out


def main() -> None:
    write_modules()
    cases = _build_cases_clean()
    # drop broken build_cases
    board = {
        "description": (
            "HARD verify board: 50 diverse tough cases. Large must sets = lots of "
            "related code to collect. must_not includes on-path siblings, shared hubs, "
            "and adversarial wording. correct <=> must⊆hot AND hot∩must_not=∅. "
            "Gold from fixture source, not tracer output."
        ),
        "hot_threshold": 0.45,
        "cases": cases,
    }
    path = ROOT / "verify_hard.json"
    path.write_text(json.dumps(board, indent=2), encoding="utf-8")
    families = {c["family"] for c in cases}
    print(f"wrote modules + {path} cases={len(cases)} families={len(families)}")
    print(f"must sizes: min={min(len(c['must']) for c in cases)} "
          f"median={sorted(len(c['must']) for c in cases)[25]} "
          f"max={max(len(c['must']) for c in cases)}")


if __name__ == "__main__":
    main()
