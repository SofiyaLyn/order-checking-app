"""Generate synthetic examples, run the checker, and write an offline HTML report."""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from launch import configure
configure()
import case_cards
import check_orders
import make_samples
HERE = Path(__file__).resolve().parent

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "demo" / "output")
    args = parser.parse_args(argv)
    inbox = HERE / "demo" / "inbox"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    make_samples.create_samples(inbox)
    console = io.StringIO()
    with redirect_stdout(console):
        code = check_orders.main([str(inbox), "--demo-auth", "--output", str(output)])
    (output / "run_console.txt").write_text(console.getvalue(), encoding="utf-8")
    if code not in (None, 0):
        print(console.getvalue())
        return int(code)
    cases = json.loads((output / "cases.json").read_text(encoding="utf-8"))
    report = case_cards.write_html(cases=cases, path=output / "order_check_cases.html")
    counts = Counter(case["decision"] for case in cases)
    print("SYNTHETIC DEMO: sender authentication and receipt times are simulated.")
    print("No mailbox connection, approval action, order submission or execution.")
    print(f"Checked {len(cases)} example emails.")
    for status in check_orders.DECISION_LABEL:
        print(f"  {check_orders.DECISION_LABEL[status]}: {counts.get(status, 0)}")
    print(f"\nOpen this report: {report}")
    print(f"Detailed results: {output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

