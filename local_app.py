"""Run the offline order checker through a loopback-only browser interface.

The form and bundled scenarios are explicitly synthetic. Uploaded email files
never establish sender authenticity from their own headers. No request can
approve, release or execute an order, and uploads live only in temporary files.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import secrets
import tempfile
import threading
from urllib.parse import urlsplit
import webbrowser
from zoneinfo import ZoneInfo

import check_orders
import make_samples
from openpyxl import Workbook

HERE = Path(__file__).resolve().parent
MAX_REQUEST_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES = 20
MAX_BODY_CHARS = 100000


class InputError(ValueError):
    """An invalid browser request, rather than an internal server failure."""


class PayloadTooLarge(InputError):
    pass


def _json_default(value):
    # Invalid workbook cell types remain visible as their original text. They
    # cannot become ready because the engine independently validates each type.
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _case_from_mail(mail, earlier):
    order = check_orders.read_order(mail)
    result = check_orders.check_mail(mail, order, earlier)
    case = {
        "file": mail["file"], "time": mail["time"], "received_at": mail["received_at"],
        "from": mail["from"], "subject": mail["subject"], "original_body": mail["body"],
        "order_ref": mail["order_ref"], "source_sha256": mail["source_sha256"],
        "message_id": mail["message_id"], "auth_mode": mail["auth_mode"],
        "demo_auth": mail["demo_auth"], "source": order["source"],
        "type": order["cls"], "lines": order["lines"],
        **{k: v for k, v in result.items() if k != "checks"},
        "checks": [{"status": s, "label": label, "detail": detail}
                   for s, label, detail in result["checks"]],
    }
    return json.loads(json.dumps(case, default=_json_default))


def _assess_paths(paths, *, demo_auth=False):
    parsed, failures = [], []
    for path in paths:
        try:
            parsed.append(check_orders.read_eml(path, demo_auth=demo_auth))
        except Exception as exc:
            failures.append(check_orders._error_case(path, exc))
    parsed.sort(key=lambda m: m["sort_key"])
    cases = []
    for mail in parsed:
        try:
            cases.append(_case_from_mail(mail, cases))
        except Exception as exc:
            path = next(p for p in paths if p.name == mail["file"])
            cases.append(check_orders._error_case(path, exc))
    cases.extend(failures)
    return cases


def _reference_data():
    return {
        "clients": [{"account": account, "name": client["name"],
                     "signers": sorted(client["signers"])}
                    for account, client in check_orders.CLIENTS.items()],
        "instruments": [{"isin": isin, "name": instrument["name"],
                         "currency": instrument["currency"],
                         "restricted": isin in check_orders.RESTRICTED}
                        for isin, instrument in check_orders.INSTRUMENTS.items()],
        "timezone": check_orders.BUSINESS_TIMEZONE,
        "illustrative_cutoff": check_orders.CUTOFF,
    }


def run_samples():
    """Recompute every sample through the same engine as the command-line app."""
    with tempfile.TemporaryDirectory(prefix="order-check-samples-") as directory:
        directory = Path(directory)
        paths = make_samples.create_samples(directory)
        manifest = json.loads((directory / "sample_manifest.json").read_text(encoding="utf-8"))
        return {"cases": _assess_paths(paths, demo_auth=True), "manifest": manifest,
                "reference": _reference_data(), "mode": "synthetic"}


def _text(data, key, *, default="", limit=2000):
    value = data.get(key, default)
    if not isinstance(value, str):
        raise InputError(f"{key} must be text")
    if len(value) > limit:
        raise PayloadTooLarge(f"{key} exceeds the {limit:,}-character limit")
    return value


def _decode_file(data, *, suffix):
    if not isinstance(data, dict):
        raise InputError("Each file must have a name and base64 data")
    name = data.get("name")
    encoded = data.get("data_base64")
    if not isinstance(name, str) or not name.strip() or len(name) > 255:
        raise InputError("A file needs a name of at most 255 characters")
    name = Path(name.replace("\\", "/")).name
    if not name.lower().endswith(suffix):
        raise InputError(f"Only {suffix} files are supported here")
    if not isinstance(encoded, str):
        raise InputError("File data must use base64 text")
    if len(encoded) > ((MAX_FILE_BYTES + 2) // 3) * 4:
        raise PayloadTooLarge("A file exceeds the 10 MiB upload limit")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InputError("File data is not valid base64") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise PayloadTooLarge("A file exceeds the 10 MiB upload limit")
    return name, raw


def check_synthetic_form(data):
    """Construct marked test input. This endpoint never validates a real sender."""
    sender = _text(data, "sender", default="anna.mueller@mueller-fo.com", limit=320)
    subject = _text(data, "subject", default="Synthetic instruction", limit=2000)
    body = _text(data, "body", limit=MAX_BODY_CHARS)
    stamp = _text(data, "received_at", default="2026-11-13T10:00:00+01:00", limit=100)
    failure = data.get("simulate_auth_failure", False)
    if not isinstance(failure, bool):
        raise InputError("simulate_auth_failure must be true or false")
    try:
        receipt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if receipt.tzinfo is None:
            receipt = receipt.replace(tzinfo=ZoneInfo(check_orders.BUSINESS_TIMEZONE))
        receipt = receipt.astimezone(ZoneInfo(check_orders.BUSINESS_TIMEZONE))
    except (ValueError, OverflowError) as exc:
        raise InputError("received_at must be an ISO date and time") from exc
    message = EmailMessage()
    try:
        message["From"] = sender
        message["To"] = "orders@firm.example"
        message["Subject"] = subject
        message["Date"] = format_datetime(receipt)
        message["X-Order-Check-Demo"] = check_orders.DEMO_MARKER
        auth = "fail" if failure else "pass"
        message["Authentication-Results"] = f"synthetic.example; spf={auth}; dkim={auth}"
        digest = hashlib.sha256((sender + subject + body + stamp).encode("utf-8")).hexdigest()
        message["Message-ID"] = f"<synthetic-{digest[:24]}@sample.test>"
        message.set_content(body)
    except (ValueError, TypeError) as exc:
        raise InputError("Sender or subject contains an invalid email header value") from exc
    attachment = data.get("attachment")
    if attachment is not None:
        name, raw = _decode_file(attachment, suffix=".xlsx")
        message.add_attachment(raw, maintype="application",
                               subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               filename=name)
    with tempfile.TemporaryDirectory(prefix="order-check-form-") as directory:
        path = Path(directory) / "synthetic_instruction.eml"
        path.write_bytes(bytes(message))
        try:
            mail = check_orders.read_eml(path, demo_auth=True)
            case = _case_from_mail(mail, [])
        except Exception as exc:
            case = check_orders._error_case(path, exc)
        return {"case": case}


def check_local_files(data):
    files = data.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise InputError("Select between 1 and 20 .eml files")
    decoded = [_decode_file(file, suffix=".eml") for file in files]
    if sum(len(raw) for _, raw in decoded) > MAX_REQUEST_BYTES:
        raise PayloadTooLarge("The combined upload exceeds 20 MiB")
    with tempfile.TemporaryDirectory(prefix="order-check-upload-") as directory:
        paths = []
        names = {}
        for index, (name, raw) in enumerate(decoded, 1):
            # Prefixes prevent same-name files from overwriting each other.
            path = Path(directory) / f"{index:03d}_{name}"
            path.write_bytes(raw)
            paths.append(path)
            names[path.name] = name
        cases = _assess_paths(paths, demo_auth=False)
        for case in cases:
            case["file"] = names.get(case["file"], case["file"])
        return {"cases": cases, "mode": "unverified-local-files",
                "note": "Uploaded headers and sender dates do not establish trusted authentication or receipt times."}


def _template_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Orders"
    sheet.append(["Account", "Side", "ISIN", "Units"])
    sheet.append(["100234", "BUY", "IE00WRLD0013", 10])
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port):
        super().__init__(("127.0.0.1", port), Handler)
        self.session_token = secrets.token_urlsafe(32)
        self.base_url = f"http://127.0.0.1:{self.server_address[1]}"


class Handler(BaseHTTPRequestHandler):
    server_version = "OrderCheckLocal/1.0"

    def log_message(self, format, *args):
        pass

    def _allowed_host(self):
        port = self.server.server_address[1]
        return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _respond(self, status, body, content_type, *, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, data):
        self._respond(status, json.dumps(data, ensure_ascii=False, default=_json_default).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status, message):
        self._json(status, {"error": message})

    def do_GET(self):
        if not self._allowed_host():
            self._error(403, "Only the local app address is allowed")
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/health":
                self._json(200, {"status": "ok", "mode": "local", "engine": "order-check"})
            elif path == "/api/samples":
                self._json(200, run_samples())
            elif path == "/api/template":
                self._respond(200, _template_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename="order_template.xlsx")
            elif path in {"/", "/index.html", "/START_HERE.html"}:
                html = (HERE / "index.html").read_text(encoding="utf-8")
                self._respond(200, html.replace("__SESSION_TOKEN__", self.server.session_token).encode("utf-8"), "text/html; charset=utf-8")
            elif path in {"/app.js", "/styles.css", "/demo_cases.js"}:
                file = HERE / path.lstrip("/")
                if not file.is_file():
                    self._error(404, "App asset not found")
                    return
                kind = "text/css" if file.suffix == ".css" else "text/javascript"
                self._respond(200, file.read_bytes(), kind + "; charset=utf-8")
            else:
                self._error(404, "Page not found")
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self._error(500, "The local app could not complete this request")

    def _request_json(self):
        if not self._allowed_host():
            raise PermissionError("Only the local app address is allowed")
        token = self.headers.get("X-Order-Check-Token", "")
        try:
            token_matches = hmac.compare_digest(token, self.server.session_token)
        except TypeError:
            token_matches = False
        if not token_matches:
            raise PermissionError("Refresh the local app before running a check")
        origin = self.headers.get("Origin")
        port = self.server.server_address[1]
        if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            raise PermissionError("This request did not come from the local app")
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise InputError("Use a JSON request")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as exc:
            raise InputError("A valid request length is required") from exc
        if length < 0:
            raise InputError("Request length cannot be negative")
        if length > MAX_REQUEST_BYTES:
            raise PayloadTooLarge("The request exceeds 20 MiB")
        try:
            data = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InputError("The request is not valid JSON") from exc
        if not isinstance(data, dict):
            raise InputError("The JSON request must be an object")
        return data

    def do_POST(self):
        path = urlsplit(self.path).path
        try:
            data = self._request_json()
            if path == "/api/check":
                self._json(200, check_synthetic_form(data))
            elif path == "/api/files":
                self._json(200, check_local_files(data))
            else:
                self._error(404, "Endpoint not found")
        except PermissionError as exc:
            self._error(403, str(exc))
        except PayloadTooLarge as exc:
            self._error(413, str(exc))
        except InputError as exc:
            self._error(400, str(exc))
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            self._error(500, "The input could not be assessed. Check the file or instruction and try again.")


def create_server(port=0):
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("Port must be an integer between 0 and 65535")
    return LocalServer(port)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="Local port, or 0 to select an available port")
    parser.add_argument("--no-browser", action="store_true", help="Print the local URL without opening a browser")
    args = parser.parse_args(argv)
    server = create_server(args.port)
    print("Order Check is running on this computer only.", flush=True)
    print(server.base_url, flush=True)
    print("Keep this window open. Press Ctrl+C to stop the app.", flush=True)
    if not args.no_browser:
        timer = threading.Timer(0.3, webbrowser.open, args=(server.base_url,))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nOrder Check stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
