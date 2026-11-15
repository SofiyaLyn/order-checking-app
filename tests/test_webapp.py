"""Local HTTP integration tests for the HTML interface.

These tests contact only the loopback server they start. Every uploaded example
and every order instruction is synthetic. No mailbox or execution service exists.
"""
from __future__ import annotations

import base64
from email.message import EmailMessage
from html.parser import HTMLParser
import http.client
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import local_app


class _SessionMeta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name") == "app-session":
            self.token = attrs.get("content")


class LocalWebAppTests(unittest.TestCase):
    BODY = "Please buy 10 units of IE00WRLD0013 for account 100234."

    @classmethod
    def setUpClass(cls):
        cls.server = local_app.create_server(port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_address[1])
        with urlopen(cls.base + "/", timeout=10) as response:
            cls.index = response.read().decode("utf-8")
            cls.index_headers = response.headers
        meta = _SessionMeta()
        meta.feed(cls.index)
        if not meta.token or meta.token == "__SESSION_TOKEN__":
            raise AssertionError("The server must inject an app-session token into the HTML")
        cls.token = meta.token

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path, *, method="GET", payload=None, raw=None,
                token=True, origin=True, headers=None):
        sent_headers = dict(headers or {})
        if payload is not None:
            raw = json.dumps(payload).encode("utf-8")
        if method == "POST":
            sent_headers.setdefault("Content-Type", "application/json")
            if token is True:
                sent_headers["X-Order-Check-Token"] = self.token
            elif isinstance(token, str):
                sent_headers["X-Order-Check-Token"] = token
            if origin is True:
                sent_headers["Origin"] = self.base
            elif isinstance(origin, str):
                sent_headers["Origin"] = origin
        request = Request(self.base + path, data=raw, headers=sent_headers, method=method)
        try:
            response = urlopen(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            status, body, received = response.status, response.read(), response.headers
        return status, body, received

    def json_request(self, path, **kwargs):
        status, body, headers = self.request(path, **kwargs)
        return status, json.loads(body.decode("utf-8")), headers

    def instruction(self, **changes):
        data = {
            "sender": "anna.mueller@mueller-fo.com",
            "subject": "Order",
            "body": self.BODY,
            "received_at": "2026-11-13T10:00",
            "simulate_auth_failure": False,
        }
        data.update(changes)
        return data

    def eml(self, body=None):
        message = EmailMessage()
        message["From"] = "anna.mueller@mueller-fo.com"
        message["To"] = "orders@firm.example"
        message["Subject"] = "Order"
        message["Date"] = "Fri, 13 Nov 2026 10:00:00 +0100"
        message["Message-ID"] = "<local-http-regression@sample.test>"
        message["Authentication-Results"] = "mx.firm.example; spf=pass; dkim=pass"
        message["X-Order-Check-Demo"] = "synthetic-v2"
        message.set_content(body or self.BODY)
        return bytes(message)

    @staticmethod
    def upload(name, blob):
        return {"name": name, "data_base64": base64.b64encode(blob).decode("ascii")}

    def test_health_is_available_only_on_the_loopback_bind(self):
        self.assertEqual("127.0.0.1", self.server.server_address[0])
        status, data, _ = self.json_request("/api/health")
        self.assertEqual(200, status)
        self.assertEqual("ok", data["status"])

    def test_index_contains_a_runtime_session_token(self):
        self.assertTrue(self.token)
        self.assertNotEqual("__SESSION_TOKEN__", self.token)
        self.assertNotIn("__SESSION_TOKEN__", self.index)

    def test_frontend_assets_are_served_with_the_expected_types(self):
        for path, expected_type in [("/app.js", "javascript"), ("/styles.css", "text/css"),
                                    ("/demo_cases.js", "javascript")]:
            with self.subTest(path=path):
                status, body, headers = self.request(path)
                self.assertEqual(200, status)
                self.assertTrue(body)
                self.assertIn(expected_type, headers.get("Content-Type", ""))

    def test_samples_return_all_scenarios_and_fictional_reference_data(self):
        status, data, _ = self.json_request("/api/samples")
        self.assertEqual(200, status)
        self.assertEqual(18, len(data["cases"]))
        self.assertEqual(18, len(data["manifest"]["scenarios"]))
        self.assertTrue(data["reference"]["clients"])
        self.assertTrue(data["reference"]["instruments"])
        for case in data["cases"]:
            if case["decision"] == "ready":
                self.assertFalse(any(check["status"] == "FAIL" for check in case["checks"]))

    def test_downloaded_template_is_a_readable_supported_workbook(self):
        status, blob, headers = self.request("/api/template")
        self.assertEqual(200, status)
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        workbook = load_workbook(io.BytesIO(blob), read_only=True)
        try:
            rows = list(workbook.active.values)
            self.assertEqual(("Account", "Side", "ISIN", "Units"), rows[0])
            self.assertEqual("BUY", rows[1][1])
            self.assertGreater(rows[1][3], 0)
        finally:
            workbook.close()

    def test_supported_synthetic_instruction_reaches_candidate_status(self):
        status, data, _ = self.json_request("/api/check", method="POST", payload=self.instruction())
        self.assertEqual(200, status)
        self.assertEqual("ready", data["case"]["decision"])
        self.assertEqual("synthetic-demo", data["case"]["auth_mode"])

    def test_ambiguous_synthetic_instruction_requires_review(self):
        status, data, _ = self.json_request("/api/check", method="POST", payload=self.instruction(
            body="Please sell half of my US funds."))
        self.assertEqual(200, status)
        self.assertNotEqual("ready", data["case"]["decision"])

    def test_simulated_authentication_failure_is_not_a_candidate(self):
        status, data, _ = self.json_request("/api/check", method="POST", payload=self.instruction(
            simulate_auth_failure=True))
        self.assertEqual(200, status)
        self.assertEqual("blocked", data["case"]["decision"])

    def test_supported_template_can_be_checked_as_a_synthetic_attachment(self):
        _, template, _ = self.request("/api/template")
        status, data, _ = self.json_request("/api/check", method="POST", payload=self.instruction(
            body="Please process the attached instruction.", attachment=self.upload("order.xlsx", template)))
        self.assertEqual(200, status)
        self.assertEqual("ready", data["case"]["decision"])

    def test_uploaded_authentication_headers_never_establish_trust(self):
        status, data, _ = self.json_request("/api/files", method="POST", payload={
            "files": [self.upload("sample.eml", self.eml())]})
        self.assertEqual(200, status)
        self.assertEqual(1, len(data["cases"]))
        self.assertNotEqual("ready", data["cases"][0]["decision"])
        self.assertNotEqual("synthetic-demo", data["cases"][0]["auth_mode"])

    def test_one_malformed_uploaded_email_does_not_abort_the_batch(self):
        status, data, _ = self.json_request("/api/files", method="POST", payload={"files": [
            self.upload("good.eml", self.eml()),
            self.upload("broken.eml", b"From: bad\nDate: invalid\n\nBroken input"),
        ]})
        self.assertEqual(200, status)
        self.assertEqual(2, len(data["cases"]))
        self.assertTrue(all(case["decision"] != "ready" for case in data["cases"]))

    def test_missing_post_token_is_rejected(self):
        status, data, _ = self.json_request("/api/check", method="POST", payload=self.instruction(), token=False)
        self.assertEqual(403, status)
        self.assertTrue(data["error"])

    def test_incorrect_post_token_is_rejected(self):
        status, data, _ = self.json_request("/api/check", method="POST", payload=self.instruction(), token="wrong")
        self.assertEqual(403, status)
        self.assertTrue(data["error"])

    def test_foreign_origin_cannot_submit_to_the_local_checker(self):
        status, data, _ = self.json_request("/api/check", method="POST", payload=self.instruction(),
                                          origin="https://other.example")
        self.assertEqual(403, status)
        self.assertTrue(data["error"])

    def test_malformed_json_produces_a_client_error(self):
        status, data, _ = self.json_request("/api/check", method="POST", raw=b"{not-json")
        self.assertEqual(400, status)
        self.assertTrue(data["error"])

    def test_non_object_json_payload_is_rejected(self):
        status, data, _ = self.json_request("/api/check", method="POST", payload=["not", "an", "instruction"])
        self.assertEqual(400, status)
        self.assertTrue(data["error"])

    def test_invalid_base64_is_rejected_before_file_processing(self):
        status, data, _ = self.json_request("/api/files", method="POST", payload={
            "files": [{"name": "bad.eml", "data_base64": "not valid ***"}]})
        self.assertEqual(400, status)
        self.assertTrue(data["error"])

    def test_empty_file_batch_is_rejected(self):
        status, data, _ = self.json_request("/api/files", method="POST", payload={"files": []})
        self.assertEqual(400, status)
        self.assertTrue(data["error"])

    def test_unsupported_upload_extension_is_rejected(self):
        status, data, _ = self.json_request("/api/files", method="POST", payload={
            "files": [self.upload("script.exe", b"synthetic")]})
        self.assertEqual(400, status)
        self.assertTrue(data["error"])

    def test_file_count_limit_is_enforced(self):
        status, data, _ = self.json_request("/api/files", method="POST", payload={
            "files": [self.upload(f"sample-{i}.eml", self.eml()) for i in range(21)]})
        self.assertIn(status, {400, 413})
        self.assertTrue(data["error"])

    def test_oversized_request_is_rejected_without_waiting_for_its_body(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            connection.putrequest("POST", "/api/check")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(20 * 1024 * 1024 + 1))
            connection.putheader("X-Order-Check-Token", self.token)
            connection.putheader("Origin", self.base)
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(413, response.status)
            self.assertTrue(json.loads(response.read())["error"])
        finally:
            connection.close()

    def test_static_routes_do_not_expose_sources_or_parent_paths(self):
        for path in ["/check_orders.py", "/README.md", "/../check_orders.py", "/%2e%2e/check_orders.py"]:
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertEqual(404, status)

    def test_there_is_no_order_execution_endpoint(self):
        status, _, _ = self.request("/api/execute", method="POST", payload={})
        self.assertIn(status, {404, 405})

    def test_unsupported_method_does_not_run_a_check(self):
        status, _, _ = self.request("/api/check", method="PUT", raw=b"{}")
        self.assertIn(status, {404, 405, 501})

    def test_html_blocks_external_scripts_and_framing(self):
        policy = self.index_headers.get("Content-Security-Policy", "")
        self.assertIn("'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)


if __name__ == "__main__":
    unittest.main()
