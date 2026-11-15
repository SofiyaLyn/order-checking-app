"""Offline order-intake decision aid with explicit validation and synthetic demos.

No mailbox connection, approval action or execution capability exists here.  ``ready``
means a candidate for independent manual controls, never permission to send an order.
The fictional balances, prices, restriction and deadline below illustrate controls.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime, time, timezone
from decimal import Decimal, InvalidOperation
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

BUSINESS_TIMEZONE = "Europe/Vienna"
CUTOFF = "16:00"  # Illustrative policy, not an Erste or instrument-specific deadline.
DEMO_MARKER = "synthetic-v2"
MAX_EMAIL_BYTES = 10 * 1024 * 1024
MAX_WORKBOOK_BYTES = 5 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
MAX_ORDER_ROWS = 1000

INSTRUMENTS = {
    "IE00WRLD0013": {"name": "World Equity ETF", "px": "98.40", "currency": "EUR"},
    "IE00ALLW0020": {"name": "All-World Equity ETF", "px": "128.10", "currency": "EUR"},
    "IE00SP5H0031": {"name": "US 500 ETF", "px": "640.20", "currency": "EUR"},
    "DE00DAXX0046": {"name": "German DAX ETF", "px": "185.30", "currency": "EUR"},
    "IE00BOND0050": {"name": "Euro Government Bond ETF", "px": "126.90", "currency": "EUR"},
}
RESTRICTED = {"DE00DAXX0046"}  # Fictional restriction for the demonstration.
CLIENTS = {
    "100234": {"name": "Mueller Family Office", "signers": {
        "anna.mueller@mueller-fo.com", "thomas.keller@mueller-fo.com"},
        "cash": 250000, "pos": {"IE00ALLW0020": 900, "IE00WRLD0013": 1500}},
    "100871": {"name": "Hartmann Stiftung", "signers": {
        "m.hartmann@hartmann-stiftung.de"}, "cash": 80000, "pos": {"IE00SP5H0031": 300}},
    "100455": {"name": "Brandt Vermoegen", "signers": {
        "j.brandt@brandt-vermoegen.at"}, "cash": 40000,
        "pos": {"IE00SP5H0031": 1200, "IE00BOND0050": 2000}},
}
DECISION_LABEL = {
    "ready": "Candidate for manual approval", "review": "Human review",
    "rejected": "Rejected: validation failure", "blocked": "Blocked: authorization/security",
    "hold": "Held: possible duplicate",
}
ISIN_RE = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")
SIDE_RE = re.compile(r"\b(buy|purchase|sell|redeem)\b", re.I)
NUMBER_RE = re.compile(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\Z")


def valid_isin(isin: str) -> bool:
    """Validate format and checksum only, not existence or permission to trade."""
    if not isinstance(isin, str) or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n *= 2
            n = n // 10 + n % 10
        total += n
    return total % 10 == 0


def client_by_sender(address: str):
    matches = [a for a, c in CLIENTS.items() if address.lower() in c["signers"]]
    return matches[0] if len(matches) == 1 else None


def _aware(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(ZoneInfo(BUSINESS_TIMEZONE))


def _decimal(value):
    """Accept an unambiguous finite decimal, never silently truncate or round."""
    if isinstance(value, bool) or value is None:
        return None
    token = str(value).strip()
    if not NUMBER_RE.fullmatch(token):
        return None
    try:
        result = Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _money(value):
    v = _decimal(value)
    return format(v, "f") if v is not None else value


def _new_line(account=None, side=None, isin=None, qty=None, amount=None):
    return {"account": account, "side": side, "isin": isin, "qty": qty,
            "amount": amount, "inferred": False, "all": False, "half": False,
            "extraction": {}, "parse_issues": []}


def read_eml(path: Path, *, demo_auth=False, received_at=None) -> dict:
    """Parse a local email. Raw Authentication-Results and Date are untrusted.

    ``received_at`` is an explicit ingestion-adapter argument, never extracted
    from body text. Only an independently trusted adapter may supply it in a real
    deployment. Demo mode uses a fixture's Date only as a simulated receipt time.
    """
    path = Path(path)
    if path.stat().st_size > MAX_EMAIL_BYTES:
        raise ValueError("Email exceeds the prototype's 10 MiB limit")
    raw = path.read_bytes()
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    issues = []
    if len(msg.get_all("From", [])) != 1:
        issues.append("Missing or multiple From headers")
    if msg.defects:
        issues.append("Malformed email structure")
    part = msg.get_body(preferencelist=("plain",))
    body = part.get_content() if part is not None else ""
    if not isinstance(body, str):
        body = ""
        issues.append("Body is not readable plain text")
    if part is None:
        issues.append("No plain-text instruction available")
    attachments = [{"name": p.get_filename() or "", "data": p.get_payload(decode=True) or b""}
                   for p in msg.iter_attachments()]
    simulated = bool(demo_auth and msg.get("X-Order-Check-Demo", "") == DEMO_MARKER)
    auth = " ".join(str(x) for x in msg.get_all("Authentication-Results", []))
    spf = re.search(r"\bspf=(\w+)", auth, re.I)
    dkim = re.search(r"\bdkim=(\w+)", auth, re.I)
    receipt = _aware(received_at)
    if received_at is not None and receipt is None:
        issues.append("Independent receipt timestamp must be timezone-aware")
    if simulated and receipt is None:
        try:
            receipt = _aware(parsedate_to_datetime(str(msg.get("Date", ""))))
        except (TypeError, ValueError, OverflowError):
            pass
        if receipt is None:
            issues.append("Synthetic receipt timestamp is missing or malformed")
    ref = hashlib.sha256(raw).hexdigest()
    return {"file": path.name, "order_ref": "OC-" + ref[:16], "source_sha256": ref,
            "message_id": str(msg.get("Message-ID", "")),
            "from": parseaddr(str(msg.get("From", "")))[1].lower(),
            "subject": str(msg.get("Subject", "")), "body": body,
            "time": receipt.strftime("%H:%M:%S") if receipt else "unknown",
            "received_at": receipt.isoformat() if receipt else None,
            "sort_key": receipt or datetime.max.replace(tzinfo=timezone.utc),
            "attachments": attachments, "parse_issues": issues,
            "auth_mode": "synthetic-demo" if simulated else "unverified-local-file",
            "demo_auth": simulated,
            "spf": spf.group(1).lower() if spf else "missing",
            "dkim": dkim.group(1).lower() if dkim else "missing"}


def _read_excel(att, out):
    payload = att.get("data") or b""
    if len(payload) > MAX_WORKBOOK_BYTES:
        out["errors"].append("Workbook exceeds the prototype's 5 MiB limit")
        return
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Workbook expands beyond the prototype's size limit")
        wb = load_workbook(io.BytesIO(payload), read_only=True, data_only=False)
        try:
            populated = [ws for ws in wb.worksheets if ws.max_row > 1]
            if len(populated) > 1:
                out["parse_issues"].append("Multiple populated worksheets require review")
            ws = wb.active
            rows = ws.iter_rows()
            first = next(rows, None)
            headers = [str(x.value).strip().lower() if x.value is not None else "" for x in first or []]
            if len(set(x for x in headers if x)) != len([x for x in headers if x]):
                out["errors"].append("Duplicate workbook column headers")
                return
            required = {"account", "side", "isin"}
            if not required.issubset(headers) or not ({"units", "amount"} & set(headers)):
                out["errors"].append("Workbook needs Account, Side, ISIN and Units or Amount headers")
                return
            unknown = set(headers) - {"account", "side", "isin", "units", "amount", "currency", ""}
            if unknown:
                out["parse_issues"].append("Unsupported workbook columns: " + ", ".join(sorted(unknown)))
            for row_number, row in enumerate(rows, 2):
                if row_number > MAX_ORDER_ROWS + 1:
                    out["errors"].append("Workbook exceeds the prototype's 1000-order-row limit")
                    break
                if all(c.value is None for c in row):
                    continue
                if any(cell.value is not None and
                       (column >= len(headers) or not headers[column])
                       for column, cell in enumerate(row)):
                    out["errors"].append(f"Workbook row {row_number} has data under an unnamed column")
                    continue
                if any(c.data_type in {"f", "e"} for c in row):
                    out["errors"].append(f"Workbook row {row_number} contains a formula or error cell")
                    continue
                values = {headers[i]: cell.value for i, cell in enumerate(row) if i < len(headers) and headers[i]}
                account = values.get("account")
                if isinstance(account, int) and not isinstance(account, bool):
                    account = str(account)
                elif account is not None:
                    account = str(account).strip()
                side = str(values.get("side") or "").strip().upper()
                isin = str(values.get("isin") or "").strip().upper()
                qty, amount = values.get("units"), values.get("amount")
                currency = str(values.get("currency") or "EUR").strip().upper()
                line = _new_line(account, side, isin, qty, _money(amount) if amount is not None else None)
                line["currency"] = currency
                line["extraction"] = {k: "explicit" if v is not None and v != "" else "missing"
                                      for k, v in {"account": account, "side": side, "isin": isin,
                                                   "size": qty if qty is not None else amount}.items()}
                out["lines"].append(line)
        finally:
            wb.close()
    except Exception as exc:
        out["errors"].append("Unreadable workbook: " + str(exc))
    if not out["lines"]:
        out["errors"].append("Workbook contains no supported order rows")


def read_order(mail: dict) -> dict:
    """Support one explicit free-text order or an explicit-column Excel file.

    Parsing describes what was found. It never resolves contradictory instructions
    or substitutes an inferred account, instrument, amount or quantity.
    """
    out = {"cls": "order", "source": "Free text", "lines": [], "errors": [], "parse_issues": []}
    body = str(mail.get("body") or "")
    subject = str(mail.get("subject") or "")
    context = subject + "\n" + body
    low = context.lower()
    subject_directions = {"SELL" if x.lower() in {"sell", "redeem"} else "BUY"
                          for x in SIDE_RE.findall(subject)}
    if (ISIN_RE.search(subject.upper()) or
            re.search(r"\b(?:EUR|USD|GBP|CHF|units?|shares?|account)\b", subject, re.I) or
            (subject_directions and re.search(r"\d", subject))):
        out["parse_issues"].append("Subject contains economic/account terms; reconcile them with the instruction before approval readiness")
    if re.search(r"\b(cancel|cancellation|withdraw|revoke|amend|amendment|replace|correction)\b", low):
        out["cls"] = "amendment/cancellation"
        out["parse_issues"].append("Amendment/cancellation needs original-order status and verified handling")
    if re.search(r"\b(?:do\s+not|don't|not\s+an?\s+order|hypothetical|hypothetically|consider|considering|would|could|if|question|thinking)\b", low):
        out["parse_issues"].append("Negation, conditional or inquiry wording requires interpretation")
    attachments = mail.get("attachments") or []
    books = [a for a in attachments if str(a.get("name", "")).lower().endswith(".xlsx")]
    if attachments:
        out["source"] = "Excel template" if books else "Unsupported attachment"
        if len(books) != 1 or len(attachments) != 1:
            out["parse_issues"].append("Multiple or unsupported attachments require review")
            return out
        # The subject may name a routine order. Only the body may override its terms.
        if (SIDE_RE.search(body) or ISIN_RE.search(body.upper()) or
                re.search(r"\b(?:EUR|USD|GBP|CHF)\s*\d|\d\s*(?:units|shares)\b|\baccount\s*(?:no\.?|number|#)?\s*:?\s*[A-Z0-9_-]+", body, re.I)):
            out["parse_issues"].append("Body contains actionable terms alongside a workbook; reconcile both sources")
        _read_excel(books[0], out)
        workbook_directions = {line.get("side") for line in out["lines"]}
        if subject_directions and subject_directions != workbook_directions:
            out["parse_issues"].append("Subject and workbook contain conflicting directions")
        return out
    directions = {"SELL" if x.lower() in {"sell", "redeem"} else "BUY" for x in SIDE_RE.findall(body)}
    if subject_directions and subject_directions != directions:
        out["parse_issues"].append("Subject and body contain conflicting directions")
    if not directions:
        out["cls"] = out["cls"] if out["cls"] != "order" else "question"
        out["parse_issues"].append("No explicit supported BUY/SELL instruction")
    if len(directions) > 1:
        out["parse_issues"].append("Conflicting BUY/SELL or multiple orders")
    if len(SIDE_RE.findall(body)) > 1:
        out["parse_issues"].append("Multiple trading actions require line-by-line clarification")
    # Repetition, even of the same value, can refer to distinct orders.
    isins = ISIN_RE.findall(body.upper())
    accounts = re.findall(r"\baccount\s*(?:no\.?|number|#)?\s*:?\s*([A-Z0-9_-]+)", body, re.I)
    normalized_body = " ".join(body.split())
    # Capture the entire proposed token, including unsupported separators, before
    # validating it. A numeric substring of 1e3, 1/2 or 25 000 is never a size.
    quantities = re.findall(r"\b(?:buy|purchase|sell|redeem)\s+(.+?)\s+(?:units?|shares?)\b",
                            normalized_body, re.I)
    amounts = re.findall(r"\b(EUR|USD|GBP|CHF)\s*(.+?)(?=\s+(?:of|for|in|worth)\b|$)",
                         normalized_body, re.I)
    if len(re.findall(r"\b(?:units?|shares?)\b", normalized_body, re.I)) > 1:
        out["parse_issues"].append("Multiple unit references require clarification")
    if len(isins) > 1:
        out["parse_issues"].append("Multiple instrument references require clarification")
    if len(accounts) > 1:
        out["parse_issues"].append("Multiple account references require clarification")
    if len(quantities) + len(amounts) > 1:
        out["parse_issues"].append("Multiple or conflicting size instructions require clarification")
    if re.search(r"\b(?:limit|stop|good\s+till|good\s+until|tomorrow|next\s+week)\b", low):
        out["parse_issues"].append("Order type or timing term outside the supported demo grammar")
    # A small positive grammar is the release-readiness boundary. Extraction may
    # display proposed fields from other text, but it cannot grant readiness.
    # Only known greeting/sign-off lines are discarded, never arbitrary clauses.
    instruction = body.strip()
    instruction = re.sub(r"\A(?:hi|hello|dear\s+(?:team|operations|colleagues))\s*[,!.]?\s*\n",
                         "", instruction, flags=re.I)
    instruction = re.split(r"\n\s*(?:thanks|thank\s+you|kind\s+regards|best\s+regards|regards|sincerely)\s*[,!.]?\s*(?:\n|$)",
                           instruction, maxsplit=1, flags=re.I)[0]
    instruction = " ".join(instruction.split())
    units_numeric = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)"
    numeric = units_numeric + r"(?:\.\d+)?"
    identifier = r"[A-Z]{2}[A-Z0-9]{9}[0-9]"
    size_and_instrument = (rf"(?:{units_numeric}\s+(?:units?|shares?)\s+(?:of\s+)?{identifier}"
                           rf"|(?:EUR|USD|GBP|CHF)\s*{numeric}\s+of\s+{identifier})")
    grammar = (rf"(?:please\s+)?(?:buy|purchase|sell|redeem)\s+{size_and_instrument}"
               rf"\s+(?:for\s+)?account\s*(?:no\.?|number|#)?\s*:?\s*[A-Z0-9_-]+\s*[.!]?")
    if not re.fullmatch(grammar, instruction, flags=re.I):
        out["parse_issues"].append("Instruction is outside the supported single-order grammar; obtain explicit clarification")
    line = _new_line(accounts[0].strip() if len(accounts) == 1 else None,
                     next(iter(directions)) if len(directions) == 1 else None,
                     isins[0] if len(isins) == 1 else None,
                     quantities[0] if len(quantities) == 1 else None,
                     _money(amounts[0][1]) if len(amounts) == 1 else None)
    currency_mentions = set(re.findall(r"\b(EUR|USD|GBP|CHF)\b", context, re.I))
    currencies = {x.upper() for x in currency_mentions}
    line["currency"] = amounts[0][0].upper() if len(amounts) == 1 else (next(iter(currencies)) if len(currencies) == 1 else "EUR")
    if len(currencies) > 1:
        out["parse_issues"].append("Conflicting currency references require clarification")
    line["all"] = bool(re.search(r"\ball\s+(?:of\s+(?:my|our)\s+)?holdings\b", low))
    line["half"] = bool(re.search(r"\bhalf\b", low))
    if line["all"] or line["half"]:
        out["parse_issues"].append("Relative size such as all/half requires an explicit confirmed quantity")
    line["extraction"] = {k: "explicit" if v is not None else "missing" for k, v in {
        "account": line["account"], "side": line["side"], "isin": line["isin"],
        "size": line["qty"] if line["qty"] is not None else line["amount"]}.items()}
    out["lines"].append(line)
    return out


def _fingerprint(line):
    qty = _decimal(line.get("qty"))
    amount = _decimal(line.get("amount"))
    return (line.get("account"), line.get("side"), line.get("isin"),
            str(qty.normalize()) if qty is not None else None,
            str(amount.normalize()) if amount is not None else None,
            line.get("currency", "EUR"))


def _eligible_history(earlier, current):
    day = _aware(current.get("received_at"))
    if day is None:
        return []
    result = []
    for record in earlier:
        stamp = _aware(record.get("received_at"))
        if stamp is None or stamp.date() != day.date():
            continue
        if record.get("decision") not in {"ready", "review", "hold"}:
            continue
        result.append(record)
    return result


def check_mail(mail: dict, order: dict, earlier: list) -> dict:
    """Produce a conservative recommendation. Required controls cannot be skipped."""
    res = {"checks": [], "exceptions": [], "suggestion": "", "reply": "", "decision": "", "reason": ""}
    hard, review, blocked, duplicate = False, False, False, False

    def add(status, label, detail):
        res["checks"].append((status, label, str(detail)))

    def fail(label, detail, *, security=False):
        nonlocal hard, blocked
        add("FAIL", label, detail)
        hard = True
        blocked = blocked or security
        res["exceptions"].append(label)

    def clarify(label, detail):
        nonlocal review
        add("WARN", label, detail)
        review = True
        res["exceptions"].append(label)

    simulated = mail.get("auth_mode") == "synthetic-demo"
    trusted_adapter = mail.get("auth_mode") == "trusted-ingestion-adapter"
    if not simulated and not trusted_adapter:
        clarify("Sender authentication requires verification", "Local headers do not establish email authenticity. An approved ingestion adapter must supply trusted evidence.")
    elif mail.get("spf") != "pass" or mail.get("dkim") != "pass":
        fail("Email authentication", "Synthetic/adapter authentication did not pass; verify independently.", security=True)
    else:
        add("PASS", "Simulated email authentication" if simulated else "Trusted adapter authentication", "Demo branching only, not actual verification" if simulated else "Evidence supplied by the approved ingestion adapter")
    sender = str(mail.get("from") or "").lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", sender):
        fail("Sender address", "Missing or malformed sender address", security=True)
    elif not any(sender in c["signers"] for c in CLIENTS.values()):
        fail("Sender is an authorised signer", "Address is not in the fictional authorization register", security=True)
    else:
        add("PASS", "Sender is an authorised signer", "Matches a fictional signer. Account-specific rights checked below.")
    if re.search(r"\b(?:do\s+not\s+call|don't\s+call|new\s+bank|new\s+account)\b", str(mail.get("body") or ""), re.I):
        fail("Suspicious instruction pattern", "Independent verification required through established contact details", security=True)
    elif re.search(r"\burgent\b", str(mail.get("body") or ""), re.I):
        clarify("Urgency requires review", "Urgency alone is not proof of fraud and does not permit bypassing controls")
    for issue in mail.get("parse_issues", []):
        clarify("Email parsing", issue)
    for issue in order.get("errors", []):
        fail("Order schema", issue)
    for issue in order.get("parse_issues", []):
        clarify("Instruction interpretation", issue)
    if order.get("cls") != "order":
        clarify("Instruction type", "Not a supported new order. Verify original status for amendments/cancellations.")
    lines = order.get("lines") or []
    if not lines:
        fail("Order schema", "No supported order lines found")
    receipt = _aware(mail.get("received_at"))
    if receipt is None:
        clarify("Receipt time and cut-off", "Independent timezone-aware receipt time unavailable. Raw Date header is not trusted.")
    else:
        cutoff = time.fromisoformat(CUTOFF)
        if receipt.time().replace(tzinfo=None) >= cutoff:
            clarify("After cut-off", f"{receipt.isoformat()} meets or exceeds the illustrative {CUTOFF} cut-off. Confirm the applicable handling date, do not promise execution.")
        elif receipt.weekday() >= 5:
            clarify("Business calendar", "Weekend receipt requires confirmation against the applicable instrument calendar")
        else:
            add("PASS", "Illustrative cut-off", f"{receipt.isoformat()} is before {CUTOFF} in {BUSINESS_TIMEZONE}")
    history = _eligible_history(earlier, mail)
    cash_used = defaultdict(Decimal)
    pos_used = defaultdict(Decimal)
    for prior in history:
        if prior.get("decision") != "ready":
            continue
        for line in prior.get("lines", []):
            inst = INSTRUMENTS.get(line.get("isin"))
            q, amount = _decimal(line.get("qty")), _decimal(line.get("amount"))
            if not inst:
                continue
            if line.get("side") == "BUY":
                if amount is not None and amount > 0:
                    cash_used[line.get("account")] += amount
                elif q is not None and q > 0:
                    cash_used[line.get("account")] += q * Decimal(str(inst["px"]))
            elif line.get("side") == "SELL" and q is not None and q > 0:
                pos_used[(line.get("account"), line.get("isin"))] += q
    seen = set()
    for i, line in enumerate(lines, 1):
        prefix = f"Line {i}: " if len(lines) > 1 else ""
        account, side, isin = line.get("account"), line.get("side"), line.get("isin")
        line_bad = False
        for issue in line.get("parse_issues", []):
            clarify(prefix + "Instruction interpretation", issue)
        if not account:
            clarify(prefix + "Missing account", "Obtain the account explicitly from the client")
            candidate = client_by_sender(sender)
            if candidate:
                res["suggestion"] = f"Signer is associated with sample account {candidate}. Ask the client to confirm; it has not been substituted."
            line_bad = True
        elif account not in CLIENTS:
            fail(prefix + "Account exists", f"Unknown sample account {account}")
            line_bad = True
        else:
            add("PASS", prefix + "Account exists", account)
            if sender not in CLIENTS[account]["signers"]:
                fail(prefix + "Sender may act on this account", f"Sender is not authorized for {account}", security=True)
                line_bad = True
            else:
                add("PASS", prefix + "Sender may act on this account", account)
        if side is None or side == "":
            clarify(prefix + "Missing direction", "Obtain one explicit BUY or SELL direction")
            line_bad = True
        elif side not in {"BUY", "SELL"}:
            fail(prefix + "Order direction", f"Unsupported direction {side!r}")
            line_bad = True
        if not isin:
            clarify(prefix + "Missing instrument", "Obtain one explicit instrument identifier")
            line_bad = True
        elif not valid_isin(isin):
            fail(prefix + "ISIN check digit", f"Invalid identifier {isin!r}; never auto-correct it")
            line_bad = True
        elif isin not in INSTRUMENTS:
            fail(prefix + "Instrument tradable", "Not found in the fictional instrument master")
            line_bad = True
        else:
            add("PASS", prefix + "ISIN and instrument master", f"{isin}: {INSTRUMENTS[isin]['name']}")
        if isin in RESTRICTED:
            fail(prefix + "Restricted list", "Instrument is restricted in the fictional reference data")
            line_bad = True
        elif isin in INSTRUMENTS:
            add("PASS", prefix + "Restricted list", "No fictional restriction")
        raw_qty, raw_amount = line.get("qty"), line.get("amount")
        qty, amount = _decimal(raw_qty), _decimal(raw_amount)
        if line.get("currency", "EUR") != "EUR":
            clarify(prefix + "Currency", "The sample prices and balances support EUR only; obtain the applicable currency controls")
            line_bad = True
        if raw_qty is not None and raw_amount is not None:
            clarify(prefix + "Conflicting size", "Both quantity and monetary amount were provided; confirm which instruction governs")
            line_bad = True
        elif raw_qty is None and raw_amount is None:
            clarify(prefix + "Missing size", "An explicit positive quantity or supported monetary amount is required")
            line_bad = True
        elif raw_qty is not None:
            if isinstance(raw_qty, str) and "." in raw_qty:
                clarify(prefix + "Quantity format", "Text unit quantities support unambiguous integers only; decimal-looking text requires clarification")
                line_bad = True
            elif qty is None or qty <= 0 or qty != qty.to_integral_value():
                fail(prefix + "Quantity", "Units must be a finite positive integer in this prototype; no rounding or truncation")
                line_bad = True
            else:
                line["qty"] = int(qty)
                add("PASS", prefix + "Quantity", f"{int(qty)} explicit units")
        elif amount is None or amount <= 0 or amount.as_tuple().exponent < -2:
            fail(prefix + "Monetary amount", "Amount must be a finite positive value with at most two decimal places")
            line_bad = True
        elif side == "SELL":
            clarify(prefix + "Monetary sell instruction", "Sell-by-amount sizing needs an instrument-specific workflow. No unit quantity has been invented.")
            line_bad = True
        else:
            line["amount"] = format(amount, "f")
            add("PASS", prefix + "Monetary amount", f"{line.get('currency', 'EUR')} {amount} preserved as an amount instruction, not converted into units")
        if line_bad:
            add("SKIP", prefix + "Position or cash", "Required fields or controls have not passed")
            continue
        fp = _fingerprint(line)
        matching = [p for p in history for old in p.get("lines", []) if _fingerprint(old) == fp]
        if fp in seen or matching:
            duplicate = True
            detail = "Repeated line within this email" if fp in seen else "Matches an earlier non-rejected instruction on this business date"
            add("WARN", prefix + "Possible duplicate", detail)
            res["exceptions"].append("Possible duplicate")
        else:
            add("PASS", prefix + "Duplicate check", "No matching instruction in this batch and business date")
        seen.add(fp)
        if side == "BUY":
            # Indicative resource check only. No proceeds from pending sells are credited.
            needed = amount if amount is not None else qty * Decimal(str(INSTRUMENTS[isin]["px"]))
            cash_used[account] += needed
            available = Decimal(str(CLIENTS[account]["cash"]))
            if cash_used[account] > available:
                fail(prefix + "Aggregate cash", f"Pending candidate buys plus this order need EUR {cash_used[account]}, sample cash is EUR {available}")
            else:
                add("PASS", prefix + "Aggregate cash", f"EUR {cash_used[account]} candidate total against EUR {available}; unit-order valuation uses indicative sample prices")
        else:
            pos_used[(account, isin)] += qty
            available = Decimal(str(CLIENTS[account]["pos"].get(isin, 0)))
            if pos_used[(account, isin)] > available:
                fail(prefix + "Aggregate position", f"Pending candidate sells plus this order need {pos_used[(account, isin)]} units, sample holding is {available}")
            else:
                add("PASS", prefix + "Aggregate position", f"{pos_used[(account, isin)]} candidate units against sample holding {available}")
    if blocked:
        res["decision"], res["reason"] = "blocked", "Authorization/security requires independent investigation. No order is released."
        res["reply"] = "Contact the established client contact through a known channel. Do not send this draft automatically."
    elif hard:
        res["decision"], res["reason"] = "rejected", "A required validation failed. Correct and recheck the instruction before it can become a candidate."
    elif duplicate:
        res["decision"], res["reason"] = "hold", "Possible duplicate. Operations must establish whether this is a separate intended instruction."
        res["reply"] = "Draft only: please confirm whether this is a separate instruction or a resend."
    elif review:
        res["decision"], res["reason"] = "review", "A required interpretation or verification is unresolved. Operations owns clarification."
        res["reply"] = "Draft only: please confirm the highlighted missing or ambiguous details."
    else:
        res["decision"] = "ready"
        res["reason"] = "Supported sample checks passed. This is a candidate for independent manual controls, not an approval or release."
        res["reply"] = "Draft only: we have received your instruction. Acceptance and execution require separate confirmation."
    res["exceptions"] = list(dict.fromkeys(res["exceptions"]))
    res["owner"] = "Operations"
    res["next_action"] = {"ready": "Independent manual review", "review": "Resolve highlighted issues",
                          "rejected": "Obtain corrected instruction and recheck", "blocked": "Independent authorization/security verification",
                          "hold": "Verify intent and original-order status"}[res["decision"]]
    return res


def _error_case(path, error):
    # Parsing can fail precisely because this file cannot be read, or is too big.
    # Do not repeat an unguarded read, and do not hash an oversized payload.
    digest = None
    try:
        if path.is_file() and path.stat().st_size <= MAX_EMAIL_BYTES:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        pass
    ref = "OC-" + (digest[:16] if digest else hashlib.sha256(str(path).encode()).hexdigest()[:16])
    return {"file": path.name, "order_ref": ref, "source_sha256": digest,
            "time": "unknown", "received_at": None, "from": "", "subject": "Unreadable input",
            "source": "Unreadable email", "type": "parse error", "lines": [],
            "auth_mode": "unverified-local-file", "demo_auth": False,
            "checks": [{"status": "FAIL", "label": "Email parsing", "detail": str(error)}],
            "decision": "review", "exceptions": ["Email parsing"],
            "reason": "Input could not be safely parsed. Other emails continue processing.",
            "suggestion": "", "reply": "", "owner": "Operations", "next_action": "Investigate unreadable input"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inbox", nargs="?", help="Folder containing local .eml files")
    parser.add_argument("--input", dest="input_dir", help="Alternative to positional inbox")
    parser.add_argument("--output", default="output", help="Output folder")
    parser.add_argument("--demo-auth", action="store_true", help="Simulate auth/receipt only for marked synthetic-v2 fixtures")
    args = parser.parse_args(argv)
    if args.inbox and args.input_dir:
        parser.error("Use positional inbox or --input, not both")
    inbox = Path(args.input_dir or args.inbox or "inbox")
    files = sorted(inbox.glob("*.eml"))
    if not files:
        print(f"No .eml files in {inbox.resolve()}. Run make_samples.py first.")
        return 1
    mode = "SYNTHETIC DEMO: authentication and receipt times are simulated" if args.demo_auth else "LOCAL FILE REVIEW: raw headers are not trusted"
    print(mode + ". No order can be approved, sent or executed.")
    parsed, failures = [], []
    for path in files:
        try:
            parsed.append(read_eml(path, demo_auth=args.demo_auth))
        except Exception as exc:
            failures.append(_error_case(path, exc))
    parsed.sort(key=lambda m: m["sort_key"])
    cases, earlier = [], []
    for mail in parsed:
        try:
            order = read_order(mail)
            result = check_mail(mail, order, earlier)
            case = {"file": mail["file"], "time": mail["time"], "received_at": mail["received_at"],
                    "from": mail["from"], "subject": mail["subject"], "order_ref": mail["order_ref"],
                    "source_sha256": mail["source_sha256"], "message_id": mail["message_id"],
                    "auth_mode": mail["auth_mode"], "demo_auth": mail["demo_auth"],
                    "source": order["source"], "type": order["cls"], "lines": order["lines"],
                    **{k: v for k, v in result.items() if k != "checks"},
                    "checks": [{"status": s, "label": l, "detail": d} for s, l, d in result["checks"]]}
            cases.append(case)
            earlier.append(case)
        except Exception as exc:
            cases.append(_error_case(inbox / mail["file"], exc))
    cases.extend(failures)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    rows = [{"file": c["file"], "order_ref": c["order_ref"], "time": c["time"], "from": c["from"],
             "subject": c["subject"], "decision": c["decision"], "exceptions": "; ".join(c["exceptions"]),
             "reason": c["reason"], "suggestion": c["suggestion"], "draft_reply": c["reply"],
             "owner": c["owner"], "next_action": c["next_action"]} for c in cases]
    checks = [{"file": c["file"], "check": ch["label"], "status": ch["status"], "detail": ch["detail"]}
              for c in cases for ch in c["checks"]]
    for name, data in [("results.csv", rows), ("checks.csv", checks)]:
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0]) if data else ["file", "check", "status", "detail"])
            writer.writeheader()
            writer.writerows(data)
    (out / "cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False), encoding="utf-8")
    run_id, stamp = str(uuid.uuid4()), datetime.now(timezone.utc).isoformat()
    audit_lines = []
    with (out / "audit_events.jsonl").open("a", encoding="utf-8") as f:
        for c in cases:
            event = {"run_id": run_id, "recorded_at": stamp, "mode": mode, "order_ref": c["order_ref"],
                     "source_sha256": c["source_sha256"], "file": c["file"], "decision": c["decision"],
                     "exceptions": c["exceptions"], "owner": c["owner"], "next_action": c["next_action"]}
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
            audit_lines.append(f"{stamp} | {c['order_ref']} | {c['file']} | {c['decision'].upper()}")
            print(f"{c['file']}: {DECISION_LABEL[c['decision']]}")
    # Human-readable run summary, with persistent event history kept separately.
    (out / "audit_log.txt").write_text("\n".join(audit_lines) + "\n", encoding="utf-8")
    print(f"\n{len(cases)} emails assessed. Reports: {out.resolve()}")
    print("Local history is an audit trail, not a tamper-proof ledger or persistent OMS duplicate control.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
