"""Regression scenarios for the offline order-checking decision aid.

These tests use invented instructions and synthetic authentication only. They do
not connect to a mailbox, send messages, approve instructions or execute orders.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import check_orders as checker


class CheckerRegressionTests(unittest.TestCase):
    SENDER = "anna.mueller@mueller-fo.com"
    WORLD = "IE00WRLD0013"
    ALL_WORLD = "IE00ALLW0020"
    BUY = "Please buy 10 units of IE00WRLD0013 for account 100234."
    DATE = "Fri, 13 Nov 2026 10:00:00 +0100"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.counter = 0

    def tearDown(self):
        self.tmp.cleanup()

    def message_path(self, body=None, *, rows=None, headers=None, sender=None,
                     date=None, marker=True, filename=None, attachment=None,
                     attachments=None, subject="Sample instruction"):
        self.counter += 1
        msg = EmailMessage()
        msg["From"] = sender or self.SENDER
        msg["To"] = "orders@firm.example"
        msg["Subject"] = subject
        msg["Date"] = date or self.DATE
        msg["Message-ID"] = f"<regression-{self.counter}@sample.test>"
        msg["Authentication-Results"] = "mx.firm.example; spf=pass; dkim=pass"
        if marker:
            msg["X-Order-Check-Demo"] = "synthetic-v2"
        for name, value in (headers or {}).items():
            if name in msg:
                msg.replace_header(name, value)
            else:
                msg[name] = value
        msg.set_content(self.BUY if body is None and rows is None and attachment is None else (body or "Please process the attached instruction."))
        if rows is not None:
            wb = Workbook()
            ws = wb.active
            ws.append(["Account", "Side", "ISIN", "Units"])
            for row in rows:
                ws.append(row)
            buf = io.BytesIO()
            wb.save(buf)
            attachment = buf.getvalue()
        if attachment is not None:
            msg.add_attachment(attachment, maintype="application",
                               subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               filename="orders.xlsx")
        for name, blob in attachments or []:
            msg.add_attachment(blob, maintype="application", subtype="octet-stream", filename=name)
        path = self.directory / (filename or f"mail-{self.counter:03}.eml")
        path.write_bytes(bytes(msg))
        return path

    def evaluate(self, body=None, *, earlier=None, demo=True, **kwargs):
        path = self.message_path(body, **kwargs)
        mail = checker.read_eml(path, demo_auth=demo)
        order = checker.read_order(mail)
        result = checker.check_mail(mail, order, earlier or [])
        return mail, order, result

    def history(self, body=None, **kwargs):
        mail, order, result = self.evaluate(body, **kwargs)
        self.assertEqual("ready", result["decision"], result)
        return {**mail, "lines": copy.deepcopy(order["lines"]), "decision": result["decision"]}

    def assertNotReady(self, result):
        self.assertNotEqual("ready", result["decision"], result)

    def assertReady(self, result):
        self.assertEqual("ready", result["decision"], result)
        self.assertFalse([c for c in result["checks"] if c[0] == "FAIL"], result)

    def test_complete_explicit_unit_order_is_candidate_only(self):
        _, _, result = self.evaluate()
        self.assertReady(result)
        self.assertIn("approv", (result["reason"] + checker.DECISION_LABEL["ready"]).lower())

    def test_valid_excel_order_is_ready(self):
        _, _, result = self.evaluate(rows=[["100234", "BUY", self.WORLD, 10]])
        self.assertReady(result)

    def test_eligible_sell_with_sufficient_position_is_ready(self):
        _, _, result = self.evaluate("Please sell 100 units of IE00WRLD0013 for account 100234.")
        self.assertReady(result)

    def test_isin_check_detects_typo(self):
        self.assertTrue(checker.valid_isin(self.WORLD))
        self.assertFalse(checker.valid_isin("IE00WRLD0014"))

    def test_bad_isin_instruction_cannot_be_ready(self):
        _, _, result = self.evaluate(self.BUY.replace(self.WORLD, "IE00WRLD0014"))
        self.assertNotReady(result)

    def test_restricted_instrument_failure_gates_overall_decision(self):
        with patch.object(checker, "RESTRICTED", {self.WORLD}):
            _, _, result = self.evaluate()
        self.assertNotReady(result)
        self.assertTrue(any(s == "FAIL" and "restrict" in label.lower()
                            for s, label, detail in result["checks"]))

    def test_unknown_account_cannot_skip_into_ready(self):
        _, _, result = self.evaluate(self.BUY.replace("100234", "999999"))
        self.assertNotReady(result)

    def test_sender_must_be_authorized_for_the_specific_account(self):
        _, _, result = self.evaluate(self.BUY.replace("100234", "100871"))
        self.assertNotReady(result)

    def test_unregistered_sender_cannot_be_ready(self):
        _, _, result = self.evaluate(sender="impostor@sample.test")
        self.assertNotReady(result)

    def test_malformed_sender_does_not_crash_checker(self):
        _, _, result = self.evaluate(sender="invalid-address")
        self.assertNotReady(result)

    def test_negative_excel_quantity_is_not_ready(self):
        _, _, result = self.evaluate(rows=[["100234", "BUY", self.WORLD, -10]])
        self.assertNotReady(result)

    def test_zero_excel_quantity_is_not_ready(self):
        _, _, result = self.evaluate(rows=[["100234", "BUY", self.WORLD, 0]])
        self.assertNotReady(result)

    def test_fractional_excel_quantity_is_not_silently_truncated(self):
        _, order, result = self.evaluate(rows=[["100234", "BUY", self.WORLD, 10.5]])
        self.assertNotReady(result)
        self.assertFalse(any(line.get("qty") == 10 for line in order["lines"]))

    def test_invalid_excel_direction_is_not_treated_as_buy(self):
        _, _, result = self.evaluate(rows=[["100234", "BYY", self.WORLD, 10]])
        self.assertNotReady(result)

    def test_empty_workbook_is_not_ready(self):
        _, _, result = self.evaluate(rows=[])
        self.assertNotReady(result)

    def test_missing_excel_required_field_is_not_ready(self):
        _, _, result = self.evaluate(rows=[["100234", "BUY", None, 10]])
        self.assertNotReady(result)

    def test_formula_quantity_requires_attention(self):
        _, _, result = self.evaluate(rows=[["100234", "BUY", self.WORLD, "=5+5"]])
        self.assertNotReady(result)

    def test_nonfinite_quantity_is_not_ready(self):
        _, _, result = self.evaluate(rows=[["100234", "BUY", self.WORLD, "NaN"]])
        self.assertNotReady(result)

    def test_incorrect_workbook_headers_do_not_shift_fields(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Account", "Side", "Unexpected instrument column", "Units"])
        ws.append(["100234", "BUY", self.WORLD, 10])
        stream = io.BytesIO()
        wb.save(stream)
        _, _, result = self.evaluate(attachment=stream.getvalue())
        self.assertNotReady(result)

    def test_corrupt_workbook_is_isolated_for_review(self):
        _, _, result = self.evaluate(attachment=b"not an Excel workbook")
        self.assertNotReady(result)

    def test_multiple_workbooks_require_review(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Account", "Side", "ISIN", "Units"])
        ws.append(["100234", "BUY", self.WORLD, 10])
        stream = io.BytesIO()
        wb.save(stream)
        blob = stream.getvalue()
        _, _, result = self.evaluate(attachment=blob, attachments=[("other.xlsx", blob)])
        self.assertNotReady(result)

    def test_workbook_and_conflicting_body_require_review(self):
        _, _, result = self.evaluate("Please sell 100 units of IE00ALLW0020 for account 100234.",
                                     rows=[["100234", "BUY", self.WORLD, 10]])
        self.assertNotReady(result)

    def test_mixed_buy_sell_does_not_manufacture_a_different_order(self):
        body = "Please buy 10 units of IE00WRLD0013 and sell 20 units of IE00ALLW0020 for account 100234."
        _, _, result = self.evaluate(body)
        self.assertNotReady(result)

    def test_multiple_instruments_with_one_direction_require_review(self):
        body = "Please buy 10 units of IE00WRLD0013 and 20 units of IE00ALLW0020 for account 100234."
        _, _, result = self.evaluate(body)
        self.assertNotReady(result)

    def test_multiple_quantities_for_one_instrument_require_review(self):
        body = "Please buy 10 units, actually 20 units of IE00WRLD0013 for account 100234."
        _, _, result = self.evaluate(body)
        self.assertNotReady(result)

    def test_negated_buy_instruction_is_not_ready(self):
        _, _, result = self.evaluate("Do not buy 10 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_hypothetical_question_is_not_an_order(self):
        _, _, result = self.evaluate("What would happen if I buy 10 units of IE00WRLD0013 for account 100234?")
        self.assertNotReady(result)

    def test_cancellation_is_not_new_order(self):
        _, _, result = self.evaluate("Cancel my instruction to buy 10 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_missing_account_requires_explicit_clarification(self):
        _, _, result = self.evaluate("Please buy 10 units of IE00WRLD0013.")
        self.assertNotReady(result)

    def test_missing_quantity_requires_clarification(self):
        _, _, result = self.evaluate("Please buy IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_negative_free_text_quantity_is_not_made_positive(self):
        _, _, result = self.evaluate("Please buy -10 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_fractional_free_text_quantity_is_not_truncated(self):
        _, _, result = self.evaluate("Please buy 10.5 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_exponent_unit_notation_is_not_read_as_its_last_digit(self):
        _, _, result = self.evaluate("Please buy 1e3 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_leading_decimal_units_are_not_read_as_whole_units(self):
        _, _, result = self.evaluate("Please buy .5 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_fraction_notation_is_not_read_as_its_denominator(self):
        _, _, result = self.evaluate("Please buy 1/2 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_space_grouped_units_are_not_silently_reduced(self):
        _, _, result = self.evaluate("Please buy 1 500 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_zero_amount_order_is_not_ready(self):
        _, _, result = self.evaluate("Please buy EUR 0 of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_missing_instrument_requires_clarification(self):
        _, _, result = self.evaluate("Please buy 10 units for account 100234.")
        self.assertNotReady(result)

    def test_two_accounts_require_review(self):
        _, _, result = self.evaluate(self.BUY + " Use account 100871 instead.")
        self.assertNotReady(result)

    def test_relative_size_requires_clarification(self):
        _, _, result = self.evaluate("Please sell half of my holdings in IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_amount_order_preserves_amount_and_never_creates_units(self):
        _, order, result = self.evaluate("Please buy EUR 25,000 of IE00WRLD0013 for account 100234.")
        self.assertReady(result)
        self.assertIsNone(order["lines"][0]["qty"])
        self.assertEqual(Decimal("25000"), Decimal(str(order["lines"][0]["amount"])))

    def test_amount_order_keeps_decimal_precision(self):
        _, order, result = self.evaluate("Please buy EUR 25,000.50 of IE00WRLD0013 for account 100234.")
        self.assertReady(result)
        self.assertEqual(Decimal("25000.50"), Decimal(str(order["lines"][0]["amount"])))

    def test_exponent_amount_is_not_read_as_one_euro(self):
        _, _, result = self.evaluate("Please buy EUR 1e3 of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_space_grouped_amount_is_not_read_as_twenty_five_euros(self):
        _, _, result = self.evaluate("Please buy EUR 25 000 of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_apostrophe_grouped_amount_is_not_read_as_twenty_five_euros(self):
        _, _, result = self.evaluate("Please buy EUR 25'000 of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_explicit_non_eur_workbook_units_require_currency_review(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Account", "Side", "ISIN", "Units", "Currency"])
        ws.append(["100234", "BUY", self.WORLD, 10, "USD"])
        stream = io.BytesIO()
        wb.save(stream)
        _, _, result = self.evaluate(attachment=stream.getvalue())
        self.assertNotReady(result)

    def test_populated_unnamed_workbook_column_cannot_be_ignored(self):
        wb = Workbook()
        ws = wb.active
        ws.append(["Account", "Side", "ISIN", "Units", None])
        ws.append(["100234", "BUY", self.WORLD, 10, "SELL instead"])
        stream = io.BytesIO()
        wb.save(stream)
        _, _, result = self.evaluate(attachment=stream.getvalue())
        self.assertNotReady(result)

    def test_subject_body_direction_conflict_requires_review(self):
        _, _, result = self.evaluate(subject="SELL instruction")
        self.assertNotReady(result)

    def test_plain_not_buy_is_not_treated_as_an_instruction(self):
        _, _, result = self.evaluate("Please note: not buy 10 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_never_buy_is_not_treated_as_an_instruction(self):
        _, _, result = self.evaluate("Never buy 10 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_should_i_buy_is_a_question(self):
        _, _, result = self.evaluate("Should I buy 10 units of IE00WRLD0013 for account 100234?")
        self.assertNotReady(result)

    def test_advice_request_is_not_a_trading_instruction(self):
        _, _, result = self.evaluate("Please advise whether to buy 10 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_conditional_unless_instruction_requires_interpretation(self):
        _, _, result = self.evaluate("Buy 10 units of IE00WRLD0013 for account 100234 unless the price changes.")
        self.assertNotReady(result)

    def test_future_weekday_qualifier_cannot_be_silently_dropped(self):
        _, _, result = self.evaluate("Please buy 10 units of IE00WRLD0013 for account 100234 on Monday.")
        self.assertNotReady(result)

    def test_settlement_currency_qualifier_cannot_be_silently_dropped(self):
        _, _, result = self.evaluate("Please buy 10 units of IE00WRLD0013 for account 100234, settlement currency USD.")
        self.assertNotReady(result)

    def test_simple_greeting_and_signoff_do_not_obscure_explicit_amount_order(self):
        body = "Hello,\n\nPlease buy EUR 25,000 of IE00WRLD0013 for account 100234.\n\nThanks,\nAnna Mueller"
        _, order, result = self.evaluate(body)
        self.assertReady(result)
        self.assertIsNone(order["lines"][0]["qty"])
        self.assertEqual(Decimal("25000"), Decimal(str(order["lines"][0]["amount"])))

    def test_amount_sale_is_not_sized_using_an_indicative_price(self):
        _, order, result = self.evaluate("Please sell EUR 25,000 of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)
        self.assertIsNone(order["lines"][0]["qty"])

    def test_conflicting_amount_and_units_require_review(self):
        _, _, result = self.evaluate("Please buy 10 units of IE00WRLD0013 for EUR 25,000 for account 100234.")
        self.assertNotReady(result)

    def test_multiple_lines_cannot_spend_the_same_cash_twice(self):
        _, _, result = self.evaluate(rows=[["100234", "BUY", self.WORLD, 2000],
                                          ["100234", "BUY", self.ALL_WORLD, 1000]])
        self.assertNotReady(result)

    def test_multiple_lines_cannot_sell_more_than_the_position(self):
        _, _, result = self.evaluate(rows=[["100234", "SELL", self.WORLD, 1000],
                                          ["100234", "SELL", self.WORLD, 700]])
        self.assertNotReady(result)

    def test_duplicate_lines_within_one_workbook_require_attention(self):
        _, _, result = self.evaluate(rows=[["100234", "BUY", self.WORLD, 10],
                                          ["100234", "BUY", self.WORLD, 10]])
        self.assertNotReady(result)

    def test_prior_ready_candidate_reserves_cash_for_this_batch(self):
        first = self.history("Please buy 2,000 units of IE00WRLD0013 for account 100234.")
        _, _, result = self.evaluate("Please buy 500 units of IE00ALLW0020 for account 100234.", earlier=[first])
        self.assertNotReady(result)

    def test_prior_ready_candidate_reserves_holdings_for_this_batch(self):
        first = self.history("Please sell 1,000 units of IE00WRLD0013 for account 100234.")
        _, _, result = self.evaluate("Please sell 700 units of IE00WRLD0013 for account 100234.", earlier=[first])
        self.assertNotReady(result)

    def test_pending_sale_proceeds_cannot_fund_another_order(self):
        _, _, result = self.evaluate(rows=[["100234", "SELL", self.WORLD, 1500],
                                          ["100234", "BUY", self.WORLD, 3000]])
        self.assertNotReady(result)

    def test_identical_resend_same_date_is_held(self):
        first = self.history()
        _, _, result = self.evaluate(earlier=[first])
        self.assertNotReady(result)
        self.assertIn("duplicat", str(result).lower())

    def test_same_instruction_on_a_different_date_is_not_automatically_duplicate(self):
        first = self.history(date="Thu, 12 Nov 2026 10:00:00 +0100")
        _, _, result = self.evaluate(earlier=[first])
        self.assertReady(result)

    def test_blocked_earlier_instruction_does_not_suppress_valid_order(self):
        first = self.history()
        first["decision"] = "blocked"
        _, _, result = self.evaluate(earlier=[first])
        self.assertReady(result)

    def test_rejected_earlier_instruction_does_not_reserve_or_duplicate(self):
        first = self.history()
        first["decision"] = "rejected"
        _, _, result = self.evaluate(earlier=[first])
        self.assertReady(result)

    def test_identical_source_hash_in_the_same_batch_is_not_ready_twice(self):
        source = self.message_path()
        duplicate = self.directory / "copied-message.eml"
        duplicate.write_bytes(source.read_bytes())
        first = checker.read_eml(source, demo_auth=True)
        order = checker.read_order(first)
        result = checker.check_mail(first, order, [])
        self.assertReady(result)
        first = {**first, "lines": order["lines"], "decision": result["decision"]}
        second = checker.read_eml(duplicate, demo_auth=True)
        self.assertEqual(first["source_sha256"], second["source_sha256"])
        result = checker.check_mail(second, checker.read_order(second), [first])
        self.assertNotReady(result)

    def test_utc_receipt_is_converted_to_vienna_before_cutoff(self):
        _, _, result = self.evaluate(date="Fri, 13 Nov 2026 14:30:00 +0000")
        self.assertReady(result)

    def test_utc_receipt_after_vienna_cutoff_requires_review(self):
        _, _, result = self.evaluate(date="Fri, 13 Nov 2026 15:30:00 +0000")
        self.assertNotReady(result)
        self.assertNotIn("will be executed", result.get("reply", "").lower())

    def test_cutoff_does_not_promise_next_trading_day_execution(self):
        _, _, result = self.evaluate(date="Fri, 13 Nov 2026 16:41:00 +0100")
        self.assertNotReady(result)
        self.assertNotIn("will be executed", result.get("reply", "").lower())

    def test_untrusted_saved_authentication_header_never_proves_sender(self):
        _, _, result = self.evaluate(demo=False)
        self.assertNotReady(result)

    def test_demo_flag_alone_does_not_trust_an_unmarked_email(self):
        _, _, result = self.evaluate(marker=False)
        self.assertNotReady(result)

    def test_simulated_failed_authentication_blocks_readiness(self):
        _, _, result = self.evaluate(headers={"Authentication-Results": "mx.firm.example; spf=fail; dkim=fail"})
        self.assertNotReady(result)

    def test_malformed_message_does_not_stop_processing_other_messages(self):
        inbox = self.directory / "inbox"
        output = self.directory / "output"
        inbox.mkdir()
        good = self.message_path(filename="good.eml")
        (inbox / "good.eml").write_bytes(good.read_bytes())
        (inbox / "broken.eml").write_bytes(b"From: bad\nDate: invalid\n\nBroken input")
        with contextlib.redirect_stdout(io.StringIO()):
            checker.main(["--input", str(inbox), "--output", str(output), "--demo-auth"])
        cases = json.loads((output / "cases.json").read_text())
        self.assertEqual(2, len(cases))
        by_name = {c["file"]: c for c in cases}
        self.assertEqual("ready", by_name["good.eml"]["decision"])
        self.assertNotEqual("ready", by_name["broken.eml"]["decision"])

    def test_error_case_does_not_fail_again_on_unreadable_input(self):
        source = self.directory / "unreadable.eml"
        source.write_bytes(b"synthetic")
        with patch.object(Path, "read_bytes", side_effect=PermissionError("sample permission failure")):
            result = checker._error_case(source, PermissionError("sample permission failure"))
        self.assertNotReady(result)

    def test_same_direction_subject_with_different_economic_terms_requires_review(self):
        _, _, result = self.evaluate(subject="Buy 20 units of IE00WRLD0013 for account 100234")
        self.assertNotReady(result)

    def test_workbook_body_account_must_be_reconciled(self):
        _, _, result = self.evaluate(body="Use account 100871 for the attached instruction.",
                                     rows=[["100234", "BUY", self.WORLD, 10]])
        self.assertNotReady(result)

    def test_workbook_subject_direction_must_be_reconciled(self):
        _, _, result = self.evaluate(subject="Sell order", rows=[["100234", "BUY", self.WORLD, 10]])
        self.assertNotReady(result)

    def test_workbook_subject_economic_terms_must_be_reconciled(self):
        _, _, result = self.evaluate(subject="Buy 20 units for account 100234",
                                     rows=[["100234", "BUY", self.WORLD, 10]])
        self.assertNotReady(result)

    def test_decimal_looking_free_text_whole_quantity_needs_clarification(self):
        _, _, result = self.evaluate("Please buy 1.000 units of IE00WRLD0013 for account 100234.")
        self.assertNotReady(result)

    def test_native_excel_integral_number_remains_supported(self):
        _, _, result = self.evaluate(rows=[["100234", "BUY", self.WORLD, 10.0]])
        self.assertReady(result)

    def test_report_preserves_the_currency_of_a_reviewed_amount(self):
        import case_cards
        shown = case_cards._size({"amount": "100.50", "currency": "USD"})
        self.assertIn("USD", shown)
        self.assertNotIn("EUR", shown)

    def test_report_does_not_reinterpret_an_unsupported_size(self):
        import case_cards
        shown = case_cards._size({"qty": "1e3"})
        self.assertIn("1e3", shown)
        self.assertNotIn("1,000", shown)

    def test_error_case_does_not_read_a_known_oversized_input(self):
        source = self.directory / "oversized.eml"
        source.write_bytes(b"synthetic")
        with patch.object(checker, "MAX_EMAIL_BYTES", 1), \
                patch.object(Path, "read_bytes", side_effect=AssertionError("must not reread oversized input")):
            result = checker._error_case(source, ValueError("oversized"))
        self.assertNotReady(result)


if __name__ == "__main__":
    unittest.main()
