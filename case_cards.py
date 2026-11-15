"""
Case cards: one card per email (Step 1 sender, Step 2 order, Step 3 rule checks, Step 4 decision),
as a self-contained HTML report that opens in any browser and prints to PDF (one email per page).

Reads output/cases.json (written by check_orders.py).

    import case_cards
    case_cards.write_html()                      # -> output/order_check_cases.html
    case_cards.show("03_unclear_order.eml")      # one card inside a notebook
    case_cards.show(status="review")             # all cards with one status
"""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import argparse
import hashlib
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "output"

DECISIONS = {
    "ready": "Candidate for manual approval",
    "review": "Human review",
    "hold": "Held: possible duplicate",
    "rejected": "Rejected, ask client",
    "blocked": "Blocked, security",
}
STEP1_KEYS = ("authentication", "authorised signer", "authorized signer", "fraud pattern", "sender evidence", "sender identity")

CSS = """
.oc{--ink:#17324d;--ink2:#526778;--ink3:#526778;--line:#cad7df;--surface:#ffffff;--page:#f3f6f8;--head:#eaf0f4;
  --good:#087e8b;--good-ink:#075d68;--good-bg:#e3f3f5;
  --warn:#fab219;--warn-ink:#8a5a00;--warn-bg:#fdf1d6;
  --hold:#8a8984;--hold-ink:#4a4945;--hold-bg:#efeeea;
  --serious:#ec835a;--serious-ink:#a3431c;--serious-bg:#fbe7de;
  --crit:#d03b3b;--crit-ink:#a32424;--crit-bg:#f8dede;
  color:var(--ink);font:15px/1.5 "Segoe UI",system-ui,-apple-system,sans-serif;color-scheme:light}
.oc *{box-sizing:border-box}
.oc h1{font-size:24px;margin:0 0 4px}
.oc .sub{color:var(--ink2);margin:0 0 20px;font-size:13px}
.oc .kpis{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:16px}
.oc .kpi{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 16px;min-width:150px}
.oc .kpi b{display:block;font-size:28px;line-height:1.1}
.oc .kpi span{color:var(--ink2);font-size:13px}
.oc .stack{display:flex;height:14px;border-radius:7px;overflow:hidden;gap:2px;margin:8px 0 6px;background:var(--surface)}
.oc .legend{display:flex;flex-wrap:wrap;gap:14px;font-size:13px;color:var(--ink2);margin-bottom:20px}
.oc .legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.oc .filters{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px;align-items:center}
.oc .filters button{font:inherit;font-size:13px;border:1px solid var(--line);background:var(--surface);border-radius:999px;
  padding:4px 12px;cursor:pointer;color:var(--ink)}
.oc .filters button[aria-pressed=true]{background:var(--ink);color:#fff;border-color:var(--ink)}
.oc .filters input{font:inherit;font-size:13px;border:1px solid var(--line);border-radius:8px;padding:5px 10px;min-width:220px}
.oc table.overview{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);
  border-radius:10px;overflow:hidden;margin-bottom:28px;font-size:14px}
.oc table.overview th{background:var(--head);text-align:left;font-weight:600;padding:8px 12px}
.oc table.overview td{border-top:1px solid var(--line);padding:8px 12px;vertical-align:top}
.oc table.overview a{color:inherit}
.oc .card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin:0 0 24px;max-width:820px}
.oc .card-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;border-bottom:1px solid var(--line);
  padding-bottom:12px;margin-bottom:8px}
.oc .card-head h2{font-size:17px;margin:0}
.oc .meta{color:var(--ink2);font-size:13px;overflow-wrap:anywhere}
.oc h3{font-size:16px;margin:18px 0 8px}
.oc .row{display:flex;gap:10px;align-items:baseline;margin:6px 0}
.oc .pill{flex:none;display:inline-block;min-width:44px;text-align:center;font-size:12px;font-weight:700;border-radius:999px;
  padding:1px 9px;border:1.5px solid}
.oc .PASS{color:var(--good-ink);border-color:var(--good);background:var(--good-bg)}
.oc .FAIL{color:var(--crit-ink);border-color:var(--crit);background:var(--crit-bg)}
.oc .WARN{color:var(--warn-ink);border-color:var(--warn);background:var(--warn-bg)}
.oc .SKIP{color:var(--ink2);border-color:#a8a79f;background:var(--hold-bg)}
.oc table.order{width:100%;border-collapse:separate;border-spacing:0;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.oc table.order th{background:var(--head);text-align:left;font-weight:600;padding:10px 12px}
.oc table.order td{border-top:1px solid var(--line);padding:10px 12px}
.oc .note{color:var(--ink2);font-size:13px;margin:6px 0 0}
.oc .decision{border:1.5px solid;border-radius:8px;padding:14px 16px;margin-top:8px}
.oc .decision h4{margin:0 0 6px;font-size:16px}
.oc .decision p{margin:6px 0}
.oc .chip{display:inline-block;white-space:nowrap;font-size:12px;font-weight:700;border-radius:999px;padding:2px 10px}
.oc .d-ready{--c:var(--good);--ci:var(--good-ink);--cb:var(--good-bg)}
.oc .d-review{--c:var(--warn);--ci:var(--warn-ink);--cb:var(--warn-bg)}
.oc .d-hold{--c:var(--hold);--ci:var(--hold-ink);--cb:var(--hold-bg)}
.oc .d-rejected{--c:var(--serious);--ci:var(--serious-ink);--cb:var(--serious-bg)}
.oc .d-blocked{--c:var(--crit);--ci:var(--crit-ink);--cb:var(--crit-bg)}
.oc .decision{border-color:var(--c);background:var(--cb)}
.oc .decision h4{color:var(--ci)}
.oc .chip{background:var(--c);color:#fff}
.oc .d-review .chip,.oc .chip.d-review{color:#0b0b0b}
.oc .chip.d-ready,.oc .chip.d-review,.oc .chip.d-hold,.oc .chip.d-rejected,.oc .chip.d-blocked{background:var(--c)}
.oc .muted{color:var(--ink3)}
.oc .scope{border-left:4px solid #007b98;background:#eaf4f7;padding:12px 16px;margin:16px 0 20px}
.oc .scope p{margin:3px 0}
.oc .lifecycle{padding:10px 0;border-top:1px solid var(--line);margin-top:12px}
.oc .lifecycle p{margin:5px 0}
.oc table.order{display:block;overflow-x:auto}
.oc table.order td{vertical-align:top}
.oc .extract{font-size:12px;color:var(--ink2)}
.oc .filtered-count{font-size:13px;color:var(--ink2);margin-left:auto}
@media(max-width:620px){.oc .card{padding:16px}.oc .card-head{display:block}.oc .card-head .chip{margin-top:10px}.oc table.overview{font-size:12px}.oc .filters input{min-width:160px}}
.oc .line-head{font-weight:600;font-size:14px;color:var(--ink2);margin:14px 0 4px;padding-top:8px;border-top:1px dashed var(--line)}
.oc .line-head:first-child{border-top:none;padding-top:0;margin-top:4px}
"""

PAGE_CSS = """
html{background:#f3f6f8}
body{margin:0;padding:32px 16px;background:#f3f6f8}
.oc{max-width:860px;margin:0 auto}
@media print{
  html,body{background:#fff;padding:0}
  .oc .filters,.oc .no-print{display:none!important}
  .oc .card{page-break-before:always;break-before:page;border:none;padding:0;max-width:none}
  .oc .card[hidden]{display:none}
  .oc .decision,.oc .pill,.oc .chip,.oc .track i,.oc .stack div,.oc table.order th{-webkit-print-color-adjust:exact;print-color-adjust:exact}
}
"""

SCRIPT = """
(function(){
  var buttons=document.querySelectorAll('.filters button'), q=document.getElementById('q'), current='all';
  function apply(){
    var text=(q.value||'').toLowerCase();
    document.querySelectorAll('[data-decision]').forEach(function(el){
      var okS=current==='all'||el.dataset.decision===current;
      var okT=!text||el.dataset.search.indexOf(text)>-1;
      el.hidden=!(okS&&okT);
    });
    var visible=document.querySelectorAll('section.card:not([hidden])').length;
    document.getElementById('filtered-count').textContent=visible+' of '+document.querySelectorAll('section.card').length+' shown';
  }
  buttons.forEach(function(b){b.addEventListener('click',function(){
    current=b.dataset.f; buttons.forEach(function(x){x.setAttribute('aria-pressed',x===b)}); apply();});});
  q.addEventListener('input',apply);
  apply();
})();
"""


# ---------------------------------------------------------------------------
def load_cases(run: bool = False, output_dir: Path | str | None = None) -> list:
    """Read existing output only; never silently launch ingestion or authentication."""
    if run:
        raise ValueError("Run run_demo.py or check_orders.py explicitly before loading reports.")
    path = (Path(output_dir) if output_dir else OUT) / "cases.json"
    if not path.exists():
        raise FileNotFoundError(f"No case output at {path}. Run python run_demo.py first, or provide --output-dir.")
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("cases.json must contain a list of case records.")
    return cases


def _number(value) -> str:
    """Format plain decimal tokens only; unsupported notation remains verbatim."""
    token = str(value).strip()
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", token):
        return str(value)
    try:
        n = Decimal(token)
        return format(n, ",f") if n != n.to_integral_value() else format(n, ",.0f")
    except (InvalidOperation, ValueError, TypeError):
        return str(value)


def _size(line: dict) -> str:
    parts = []
    qty = line.get("qty")
    if qty is not None:
        if isinstance(qty, int) and not isinstance(qty, bool) and qty > 0:
            parts.append(f"{qty:,} units")
        else:
            parts.append(f"{qty} units (raw input; clarify)")
    amount = line.get("amount")
    if amount is not None:
        currency = str(line.get("currency") or "EUR")
        token = str(amount).strip()
        valid = not isinstance(amount, bool) and bool(re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", token))
        if valid:
            value = Decimal(token)
            valid = value.is_finite() and value > 0
        if valid:
            parts.append(f"{currency} {value:,.2f} (amount instruction)")
        else:
            parts.append(f"{currency} {amount} (raw amount; clarify)")
    if parts:
        return "; ".join(parts)
    if line.get("all"):
        return '"all holdings" (clarify)'
    if line.get("half"):
        return '"half" (clarify)'
    return "Not supplied"


def _extraction_text(line: dict) -> str:
    if line.get("issues") or line.get("parse_issues"):
        return "Needs clarification"
    if line.get("inferred"):
        return "Inferred field requires confirmation"
    statuses = line.get("extraction")
    if isinstance(statuses, str):
        return statuses
    if isinstance(statuses, dict):
        return "; ".join(f"{key}: {value}" for key, value in statuses.items())
    return "Rule-based extraction; validate the terms"


def _case_id(case: dict) -> str:
    value = str(case.get("order_ref") or case.get("message_ref") or case.get("file", "case"))
    return "case-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _check_row(c: dict) -> str:
    label = c["label"]
    if label.startswith("Instrument tradable"):
        label = label.replace("Instrument tradable", "Instrument is tradable")
    return (f'<div class="row"><span class="pill {escape(c["status"])}">{escape(c["status"].lower())}</span>'
            f'<span><b>{escape(label)}.</b> {escape(c["detail"][:1].upper() + c["detail"][1:])}</span></div>')


def _step3_html(checks: list, lines: list) -> str:
    """Group both legacy [line N] and current Line N: check labels."""
    out, current = [], None
    for c in checks:
        m = re.match(r"^(?:\[line\s*(\d+)\]\s*|line\s*(\d+):\s*)(.*)$", c["label"], re.I)
        if not m:
            out.append(_check_row(c))
            continue
        n = int(m.group(1) or m.group(2))
        if n != current:
            current = n
            line = lines[n - 1] if n - 1 < len(lines) else {}
            desc = " ".join(x for x in [line.get("side"), _size(line), line.get("isin")] if x and x != "?")
            out.append(f'<div class="line-head">Order line {n}: {escape(desc)}</div>')
        out.append(_check_row({**c, "label": m.group(3)}))
    return "".join(out)


def card_html(case: dict) -> str:
    d = case["decision"]
    step1 = [c for c in case["checks"] if any(k.lower() in c["label"].lower() for k in STEP1_KEYS)]
    step3 = [c for c in case["checks"] if c not in step1]

    rows = []
    for line in case["lines"]:
        acc = escape(line.get("account") or "?") + (" (from sender)" if line.get("inferred") else "")
        rows.append(f"<tr><td>{acc}</td><td>{escape(line.get('side') or '?')}</td>"
                    f"<td>{escape(line.get('isin') or '?')}</td><td>{escape(_size(line))}</td>"
                    f"<td>{escape(_extraction_text(line))}</td></tr>")
    order_table = ("<table class='order'><thead><tr><th>Account</th><th>Side</th><th>ISIN</th><th>Size</th>"
                   "<th>Extraction status</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
                   if rows else "<p class='muted'>No order lines found.</p>")
    note = ("The spreadsheet is parsed using fixed rules. Parsed values still require schema, authorization and business-rule checks."
            if case["source"].lower().startswith("excel") else
            "Text extraction supports a deliberately narrow grammar. Ambiguous or unsupported wording requires review. "
            "No extraction probabilities or AI model are used.")

    extra = ""
    if case.get("suggestion"):
        extra += f"<p><b>Suggestion for the reviewer:</b> {escape(case['suggestion'])}</p>"
    if case.get("reply"):
        extra += f"<p><b>Draft reply, not sent:</b> {escape(case['reply'])}</p>"

    search = " ".join([case["file"], case["from"], case["subject"], DECISIONS.get(d, d)]).lower()
    return f"""
<section class="card" id="{_case_id(case)}" data-decision="{escape(d)}" data-search="{escape(search)}">
  <div class="card-head">
    <div><h2>{escape(case['subject'] or '(no subject)')}</h2>
      <div class="meta">{escape(case['from'])} · received {escape(case['time'])} · {escape(case['file'])}</div></div>
    <span class="chip d-{escape(d)}">{escape(DECISIONS.get(d, d))}</span>
  </div>
  <h3>Step 1. Sender evidence and authority</h3>
  {''.join(_check_row(c) for c in step1)}
  <h3>Step 2. Read the email: {escape(case['source'])}, type “{escape(case['type'])}”</h3>
  {order_table}
  <p class="note">{note}</p>
  <h3>Step 3. Rule checks</h3>
  {_step3_html(step3, case["lines"]) or "<p class='muted'>No rule-check results recorded for this case.</p>"}
  <h3>Step 4. Recommendation</h3>
  <div class="decision d-{escape(d)}">
    <h4>{escape(DECISIONS.get(d, d))}</h4>
    <p>{escape(case['reason'])}</p>
    {extra}
    <div class="lifecycle">
      <p><b>Proposed owner:</b> {escape(str(case.get('owner') or 'Operations'))}</p>
      <p><b>Next action:</b> {escape(str(case.get('next_action') or {'ready':'Independent reviewer checks the original instruction and required controls before any release.','review':'Clarify the instruction or missing evidence before progressing.','hold':'Confirm whether this is a legitimate additional order before progressing.','rejected':'Investigate the failed controls and obtain a corrected instruction.','blocked':'Verify the case through an independently established contact channel.'}.get(d,'Operations reviews this case.')))}</p>
      <p class="note">Reference: {escape(str(case.get('order_ref') or case.get('message_ref') or case.get('file', 'Not supplied')))}. Approval and external execution are outside this prototype.</p>
    </div>
  </div>
</section>"""


def _summary_html(cases: list) -> str:
    n = len(cases)
    counts = {k: sum(c["decision"] == k for c in cases) for k in DECISIONS}
    color = {"ready": "var(--good)", "review": "var(--warn)", "hold": "var(--hold)",
             "rejected": "var(--serious)", "blocked": "var(--crit)"}
    kpis = [("Emails checked", n), ("Manual-approval candidates", counts["ready"]),
            ("Need attention", n - counts["ready"]), ("Blocked, security", counts["blocked"])]
    stack = "".join(f'<div title="{DECISIONS[k]}: {v}" style="flex:{v};background:{color[k]}"></div>'
                    for k, v in counts.items() if v)
    legend = "".join(f'<span><i style="background:{color[k]}"></i>{DECISIONS[k]} <b>{v}</b></span>'
                     for k, v in counts.items())
    overview = "".join(
        f'<tr data-decision="{escape(c["decision"])}" data-search="{escape(" ".join([c["file"], c["from"], c["subject"], DECISIONS.get(c["decision"], "")]).lower())}">'
        f'<td>{escape(c["time"])}</td><td><a href="#{_case_id(c)}">{escape(c["subject"] or "(no subject)")}</a>'
        f'<div class="meta">{escape(c["from"])}</div></td>'
        f'<td><span class="chip d-{escape(c["decision"])}">{escape(DECISIONS.get(c["decision"], c["decision"]))}</span></td></tr>'
        for c in cases)
    buttons = '<button data-f="all" aria-pressed="true">All</button>' + "".join(
        f'<button data-f="{k}" aria-pressed="false">{DECISIONS[k]} ({counts[k]})</button>' for k in DECISIONS if counts[k])
    return f"""
<div class="kpis">{''.join(f'<div class="kpi"><b>{v}</b><span>{escape(l)}</span></div>' for l, v in kpis)}</div>
<div class="stack" role="img" aria-label="Review status split">{stack}</div>
<div class="legend">{legend}</div>
<div class="filters no-print">{buttons}<input id="q" type="search" aria-label="Search sender, subject or file" placeholder="Search sender, subject, file"><span class="filtered-count" id="filtered-count" aria-live="polite"></span></div>
<table class="overview"><thead><tr><th>Time</th><th>Email</th><th>Status</th></tr></thead><tbody>{overview}</tbody></table>"""


def page_html(cases: list) -> str:
    created = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Order check cases</title><style>{CSS}{PAGE_CSS}</style></head>
<body><main class="oc">
<h1>Investment order review</h1>
<p class="sub">Created {created} · {len(cases)} messages · offline decision-support prototype</p>
<div class="scope"><p><b>Demonstration scope</b></p><p>Reference data and supplied scenarios are synthetic. Authentication in demo mode is simulated, not verified against a mail server. Email headers alone do not prove authenticity.</p><p>These are recommendations for Operations. The prototype records no human approval, submits no orders and performs no execution. Sample status counts show scenario coverage, not measured accuracy or automation savings.</p></div>
{_summary_html(cases)}
{''.join(card_html(c) for c in cases)}
</main><script>{SCRIPT}</script></body></html>"""


def write_html(cases: list | None = None, path: Path | str | None = None) -> Path:
    cases = cases if cases is not None else load_cases()
    path = Path(path) if path else OUT / "order_check_cases.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page_html(cases), encoding="utf-8")
    return path


def show(file: str | None = None, status: str | None = None, cases: list | None = None):
    """Show case cards in a notebook: one file, one status, or all."""
    from IPython.display import HTML, display
    cases = cases if cases is not None else load_cases()
    picked = [c for c in cases if (file is None or c["file"] == file) and (status is None or c["decision"] == status)]
    if not picked:
        print("No matching emails. Files:", ", ".join(c["file"] for c in cases))
        return
    display(HTML(f"<style>{CSS}</style><div class='oc'>{''.join(card_html(c) for c in picked)}</div>"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render existing order-check output as offline HTML.")
    parser.add_argument("--input", "--output-dir", dest="output_dir", type=Path, default=OUT)
    args = parser.parse_args()
    print(write_html(load_cases(output_dir=args.output_dir), args.output_dir / "order_check_cases.html"))

