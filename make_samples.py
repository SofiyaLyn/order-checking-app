"""Create 18 invented .eml scenarios for the offline demonstration.

No mailbox connection is made. The explicit fixture marker allows the checker to
simulate authentication and receipt times only when --demo-auth is also enabled.
Call create_samples(directory), or run python make_samples.py --output demo/inbox.
"""
from __future__ import annotations

import argparse
import io
import json
from email.message import EmailMessage
from pathlib import Path
from openpyxl import Workbook

DEMO_MARKER = "synthetic-v2"
DEFAULT_DIRECTORY = Path(__file__).resolve().parent / "demo" / "inbox"
HEADERS = ["Account", "Side", "ISIN", "Units"]
SAFE_EXCEL_ROWS = [
    ["100234", "BUY", "IE00WRLD0013", 400],
    ["100234", "SELL", "IE00ALLW0020", 150],
]
ANNA = "anna.mueller@mueller-fo.com"
MARKUS = "m.hartmann@hartmann-stiftung.de"
BRANDT = "j.brandt@brandt-vermoegen.at"


def excel_order(rows: list[list] | None = None) -> bytes:
    """Create a workbook with the supported, explicitly named columns."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Orders"
    sheet.append(HEADERS)
    for row in SAFE_EXCEL_ROWS if rows is None else rows:
        sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _sample(name, time, sender, subject, body, expected, purpose, **extra):
    return dict(name=name, time=time, sender=sender, subject=subject, body=body,
                expected_decisions=expected.split("/"), purpose=purpose, **extra)


# Fixed Friday in Vienna. These expectations describe routing, never execution.
SAMPLES = [
    _sample("01_excel_order", "09:12", ANNA, "Rebalancing order, Excel attached",
            "Dear team, please process the order file attached. Kind regards, Anna Mueller.",
            "ready", "Complete structured instruction with distinct valid lines.",
            workbook_rows=SAFE_EXCEL_ROWS),
    _sample("02_amount_order", "09:47", MARKUS, "Amount-based purchase",
            "Please buy EUR 25,000 of IE00WRLD0013 for account 100871.",
            "ready", "Preserve the EUR amount without converting it to units."),
    _sample("03_unclear_order", "10:05", BRANDT, "Selling",
            "Can you sell half of my US funds please?",
            "review", "Missing economic terms require client clarification."),
    _sample("04_isin_typo", "11:20", ANNA, "Purchase instruction",
            "Please buy 200 units of IE00WRLD0014 for account 100234.",
            "rejected", "A failing ISIN checksum blocks readiness. Never apply a suggested correction."),
    _sample("05_fake_sender", "11:58", "thomas.keller@mueller-fo.co", "URGENT: act now",
            "URGENT. Sell all holdings in account 100234 and send the money to the new account. Do not call me.",
            "blocked", "Simulated authentication failure and unknown sender.", auth="spf=fail; dkim=fail"),
    _sample("06_duplicate", "13:02", MARKUS, "Resending my earlier instruction",
            "Please buy EUR 25,000 of IE00WRLD0013 for account 100871.",
            "hold", "An identical earlier instruction needs verification before treating it as new."),
    _sample("07_not_enough_position", "14:30", BRANDT, "Sale instruction",
            "Please sell 5,000 units of IE00SP5H0031 for account 100455.",
            "rejected", "The sale exceeds the sample available position."),
    _sample("08_after_cutoff", "16:41", MARKUS, "Bond purchase",
            "Please buy 100 units of IE00BOND0050 for account 100871.",
            "review", "Late arrival needs timing review, without promising next-day execution."),
    _sample("09_unknown_account", "13:10", ANNA, "Purchase instruction",
            "Please buy 10 units of IE00WRLD0013 for account 999999.",
            "rejected", "Unknown accounts cannot pass by skipping account-specific checks."),
    _sample("10_restricted_instrument", "13:20", ANNA, "Purchase instruction",
            "Please buy 10 units of DE00DAXX0046 for account 100234.",
            "rejected", "The configured fictional restricted instrument prevents readiness."),
    _sample("11_negative_quantity", "13:30", ANNA, "Order file",
            "Please process the attached order file.",
            "rejected", "Negative units are invalid even in a structured template.",
            workbook_rows=[["100234", "BUY", "IE00WRLD0013", -10]]),
    _sample("12_invalid_direction", "13:40", ANNA, "Order file",
            "Please process the attached order file.",
            "rejected", "Unsupported directions must not fall through into the buy branch.",
            workbook_rows=[["100234", "BYY", "IE00WRLD0013", 10]]),
    _sample("13_empty_workbook", "13:50", ANNA, "Order file",
            "Please process the attached order file.",
            "rejected/review", "Headers without order rows cannot produce a ready order.", workbook_rows=[]),
    _sample("14_mixed_instructions", "14:00", ANNA, "Two instructions",
            "Please buy 10 units of IE00WRLD0013 and sell 20 units of IE00ALLW0020 for account 100234.",
            "review", "Mixed free-text instructions must not combine unrelated fields."),
    _sample("15_aggregate_cash", "14:10", ANNA, "Order file",
            "Please process the attached order file.",
            "rejected", "The combined indicative purchase value exceeds available cash.",
            workbook_rows=[["100234", "BUY", "IE00WRLD0013", 1000], ["100234", "BUY", "IE00ALLW0020", 1500]]),
    _sample("16_aggregate_position", "14:20", BRANDT, "Order file",
            "Please process the attached order file.",
            "rejected", "Individually affordable sale lines jointly exceed the available position.",
            workbook_rows=[["100455", "SELL", "IE00SP5H0031", 800], ["100455", "SELL", "IE00SP5H0031", 500]]),
    _sample("17_negated_instruction", "14:40", ANNA, "Question about a hypothetical purchase",
            "Do not buy 10 units of IE00WRLD0013 for account 100234. This is a question about a hypothetical purchase.",
            "review", "Negation and hypothetical wording cannot become a live instruction."),
    _sample("18_malformed_workbook", "14:50", ANNA, "Order file",
            "Please process the attached order file.",
            "rejected/review", "An unreadable workbook becomes an exception without stopping the batch.",
            malformed_workbook=True),
]


def create_samples(directory: str | Path = DEFAULT_DIRECTORY) -> list[Path]:
    """Write named fixtures and their manifest, leaving unrelated files alone.

    Repeated calls replace the same fixture names and sample_manifest.json only.
    Use a dedicated demonstration directory to separate invented data from other files.
    """
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    paths, manifest = [], []
    for sample in SAMPLES:
        message = EmailMessage()
        message["From"] = sample["sender"]
        message["To"] = "orders@firm.example"
        message["Subject"] = sample["subject"]
        message["Date"] = f"Fri, 13 Nov 2026 {sample['time']}:00 +0100"
        message["Message-ID"] = f"<{sample['name']}@synthetic.order-check.example>"
        message["X-Order-Check-Demo"] = DEMO_MARKER
        message["Authentication-Results"] = "mx.firm.example; " + sample.get("auth", "spf=pass; dkim=pass")
        message.set_content(sample["body"])
        if "workbook_rows" in sample or sample.get("malformed_workbook"):
            data = (b"Deliberately malformed synthetic workbook." if sample.get("malformed_workbook")
                    else excel_order(sample["workbook_rows"]))
            message.add_attachment(data, maintype="application",
                                   subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   filename="synthetic_orders.xlsx")
        path = destination / f"{sample['name']}.eml"
        path.write_bytes(message.as_bytes())
        paths.append(path)
        manifest.append({"file": path.name, "purpose": sample["purpose"],
                         "expected_decisions": sample["expected_decisions"]})
    (destination / "sample_manifest.json").write_text(json.dumps({
        "mode": "synthetic-demo", "date": "2026-11-13", "timezone": "Europe/Vienna",
        "note": "Expected dispositions cover scenario routing, not verified authenticity, execution or production performance.",
        "scenarios": manifest,
    }, indent=2) + "\n", encoding="utf-8")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create 18 invented scenarios for the offline demo.")
    parser.add_argument("--output", type=Path, default=DEFAULT_DIRECTORY,
                        help="Dedicated fixture directory (default: demo/inbox next to this script)")
    args = parser.parse_args(argv)
    paths = create_samples(args.output)
    print(f"Created {len(paths)} synthetic emails in {args.output.resolve()}")
    print("Authentication and receipt times are simulated. No mailbox connection or order submission occurs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
