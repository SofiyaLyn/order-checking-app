"""
Presentation layer for the order checker: charts, notebook tables and an Excel report.

Reads what check_orders.py writes (output/results.csv, output/checks.csv, output/audit_log.jsonl).

In a notebook:
    import report
    r = report.load()          # run run_demo.py or check_orders.py first
    report.show(r)             # KPI line, styled tables, charts
    report.to_excel(r)         # -> output/order_check_report.xlsx

From the terminal:
    python report.py           # reads existing output, then writes charts and an Excel file
"""

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import matplotlib

if "ipykernel" not in sys.modules:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).parent
OUT = HERE / "output"

# ---------------------------------------------------------------------------
# Labels and colours
# ---------------------------------------------------------------------------
DECISIONS = {  # order = how they are shown everywhere
    "ready": "Candidate for manual approval",
    "review": "Human review",
    "hold": "Held: possible duplicate",
    "rejected": "Rejected, ask client",
    "blocked": "Blocked, security",
}
DECISION_COLOR = {  # status colours; "hold" is pending, so neutral grey
    "ready": "#087e8b",
    "review": "#fab219",
    "hold": "#8a8984",
    "rejected": "#ec835a",
    "blocked": "#d03b3b",
}
DECISION_TEXT = {k: ("#0b0b0b" if k == "review" else "#ffffff") for k in DECISIONS}

STATUS_ORDER = ["FAIL", "WARN", "PASS", "SKIP"]  # worst first
STATUS_LABEL = {"PASS": "✓ Pass", "FAIL": "✗ Fail", "WARN": "! Warn", "SKIP": "– Skip"}
STATUS_FILL = {"PASS": "#d9f0d9", "FAIL": "#f6d2d2", "WARN": "#fde7b8", "SKIP": "#ecebe7"}
STATUS_INK = {"PASS": "#006300", "FAIL": "#a32424", "WARN": "#7a5200", "SKIP": "#52514e"}

INK, INK_2, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#ffffff"
BAR = "#2a78d6"

# Check labels are grouped into these columns for the matrix (per email, worst status wins).
CHECK_GROUPS = [
    ("Email authentication", "SPF/DKIM"),
    ("authorised signer", "Authorised signer"),
    ("fraud pattern", "Fraud pattern"),
    ("All fields found", "Order read"),
    ("ISIN check digit", "ISIN"),
    ("Instrument tradable", "Tradable"),
    ("Restricted list", "Restricted list"),
    ("may act on this account", "Account mandate"),
    ("Position", "Position / cash"),
    ("Cash", "Position / cash"),
    ("Duplicate", "Duplicate"),
    ("Cut-off", "Cut-off"),
]
MATRIX_COLUMNS = list(dict.fromkeys(name for _, name in CHECK_GROUPS))


def _group(label: str) -> str:
    label = re.sub(r"^\[line \d+\]\s*", "", label)
    for key, name in CHECK_GROUPS:
        if key.lower() in label.lower():
            return name
    return label


def _style_axes(ax):
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=INK_2, length=0, labelsize=10)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
class Report:
    def __init__(self, results, checks, audit, output_dir=None):
        self.results, self.checks, self.audit = results, checks, audit
        self.output_dir = Path(output_dir) if output_dir else OUT
        self.created = datetime.now()

    @property
    def summary(self) -> pd.DataFrame:
        counts = self.results["decision"].value_counts()
        df = pd.DataFrame({"Status": list(DECISIONS.values()),
                           "Emails": [int(counts.get(k, 0)) for k in DECISIONS]})
        df["Share"] = df["Emails"] / max(len(self.results), 1)
        df.index = list(DECISIONS)
        return df

    @property
    def exceptions(self) -> pd.DataFrame:
        s = (self.results["exceptions"].fillna("").str.split("; ").explode().str.strip())
        s = s[s != ""]
        df = s.value_counts().rename_axis("Exception").reset_index(name="Emails")
        return df

    @property
    def matrix(self) -> pd.DataFrame:
        if self.checks.empty:
            return pd.DataFrame(index=self.results["file"], columns=MATRIX_COLUMNS)
        c = self.checks.assign(group=self.checks["check"].map(_group))
        rank = {s: i for i, s in enumerate(STATUS_ORDER)}
        worst = (c.assign(r=c["status"].map(rank))
                 .sort_values("r").groupby(["file", "group"])["status"].first().unstack())
        cols = [col for col in MATRIX_COLUMNS if col in worst.columns]
        cols += [col for col in worst.columns if col not in cols]
        return worst.reindex(index=self.results["file"], columns=cols)

    @property
    def emails(self) -> pd.DataFrame:
        r = self.results
        return pd.DataFrame({
            "File": r["file"], "Received": r["time"], "From": r["from"], "Subject": r["subject"],
            "Review status": r["decision"].map(DECISIONS).fillna(r["decision"]),
            "Exceptions": r["exceptions"].fillna(""), "Why": r["reason"].fillna(""),
            "Suggestion for reviewer": r["suggestion"].fillna(""), "Draft reply": r["draft_reply"].fillna(""),
            "_decision": r["decision"],
        })


def load(run: bool = False, output_dir: Path | str | None = None) -> Report:
    """Read existing reports. Ingestion and authentication are always explicit."""
    if run:
        raise ValueError("Run run_demo.py or check_orders.py explicitly before loading reports.")
    directory = Path(output_dir) if output_dir else OUT
    results_path, checks_path = directory / "results.csv", directory / "checks.csv"
    for path in [results_path, checks_path]:
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}. Run python run_demo.py first, or provide --output-dir.")
    results = pd.read_csv(results_path, dtype=str, keep_default_na=False)
    checks = pd.read_csv(checks_path, dtype=str, keep_default_na=False)
    defaults = {"file":"", "time":"", "from":"", "subject":"", "decision":"review", "exceptions":"", "reason":"", "suggestion":"", "draft_reply":""}
    for key, value in defaults.items():
        if key not in results:
            results[key] = value
    audit_path = directory / "audit_log.jsonl"
    if not audit_path.exists():
        audit_path = directory / "audit_log.txt"
    audit = audit_path.read_text(encoding="utf-8").splitlines() if audit_path.exists() else []
    return Report(results, checks, audit, output_dir=directory)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------
def fig_decisions(r: Report):
    s = r.summary.iloc[::-1]  # top-to-bottom in DECISIONS order
    fig, ax = plt.subplots(figsize=(7, 3.2), facecolor=SURFACE)
    bars = ax.barh(s["Status"], s["Emails"], height=0.55,
                   color=[DECISION_COLOR[k] for k in s.index], edgecolor=SURFACE, linewidth=2)
    for bar, n, share in zip(bars, s["Emails"], s["Share"]):
        ax.text(bar.get_width() + 0.08, bar.get_y() + bar.get_height() / 2,
                f"{n}  ({share:.0%})", va="center", fontsize=10, color=INK)
    _style_axes(ax)
    ax.set_xlim(0, max(s["Emails"].max(), 1) * 1.25)
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax.tick_params(axis="y", colors=INK)
    ax.set_title(f"Review status of {len(r.results)} emails", loc="left", fontsize=12,
                 color=INK, fontweight="bold", pad=12)
    fig.tight_layout()
    return fig


def fig_exceptions(r: Report):
    e = r.exceptions.iloc[::-1]
    fig, ax = plt.subplots(figsize=(7, max(2.2, 0.45 * len(e) + 1)), facecolor=SURFACE)
    if e.empty:
        ax.text(0.5, 0.5, "No exceptions", ha="center", va="center", color=INK_2, fontsize=12)
        ax.axis("off")
    else:
        bars = ax.barh(e["Exception"], e["Emails"], height=0.55, color=BAR, edgecolor=SURFACE, linewidth=2)
        for bar, n in zip(bars, e["Emails"]):
            ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2, str(n),
                    va="center", fontsize=10, color=INK)
        _style_axes(ax)
        ax.set_xlim(0, e["Emails"].max() * 1.2)
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
        ax.tick_params(axis="y", colors=INK)
    ax.set_title("Exceptions flagged (number of emails)", loc="left", fontsize=12,
                 color=INK, fontweight="bold", pad=12)
    fig.tight_layout()
    return fig


def fig_check_matrix(r: Report):
    m = r.matrix
    nrows, ncols = m.shape
    fig, ax = plt.subplots(figsize=(1.0 * ncols + 3.2, 0.5 * nrows + 1.6), facecolor=SURFACE)
    for i, f in enumerate(m.index):
        for j, col in enumerate(m.columns):
            st = m.iat[i, j]
            fill = STATUS_FILL.get(st, SURFACE)
            ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor=fill, edgecolor=SURFACE, linewidth=2))
            if isinstance(st, str):
                ax.text(j + 0.5, i + 0.5, STATUS_LABEL[st].split()[0], ha="center", va="center",
                        fontsize=12, color=STATUS_INK[st], fontweight="bold")
    ax.set_xlim(0, ncols)
    ax.set_ylim(nrows, 0)
    ax.set_xticks([j + 0.5 for j in range(ncols)], m.columns, rotation=35, ha="left",
                  rotation_mode="anchor", fontsize=9, color=INK)
    decision = r.results.set_index("file")["decision"]
    ax.set_yticks([i + 0.5 for i in range(nrows)],
                  [f"{f}" for f in m.index], fontsize=9, color=INK)
    for tick, f in zip(ax.get_yticklabels(), m.index):
        tick.set_color(INK)
    # decision chip on the right of each row
    for i, f in enumerate(m.index):
        k = decision.get(f, "")
        ax.text(ncols + 0.15, i + 0.5, DECISIONS.get(k, k), va="center", fontsize=9, color=INK)
        ax.add_patch(plt.Rectangle((ncols + 0.02, i + 0.2), 0.08, 0.6,
                                   facecolor=DECISION_COLOR.get(k, AXIS), clip_on=False))
    for side in ax.spines.values():
        side.set_visible(False)
    ax.tick_params(length=0)
    ax.xaxis.tick_top()
    ax.set_title("Checks per email   ✓ pass   ✗ fail   ! warning   – skipped   (blank = not run)",
                 loc="left", fontsize=10, color=INK_2, pad=70)
    fig.tight_layout()
    return fig


def save_charts(r: Report) -> dict:
    r.output_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, fn in [("decisions", fig_decisions), ("exceptions", fig_exceptions), ("checks", fig_check_matrix)]:
        fig = fn(r)
        paths[name] = r.output_dir / f"chart_{name}.png"
        fig.savefig(paths[name], dpi=150, bbox_inches="tight", facecolor=SURFACE)
        plt.close(fig)
    return paths


# ---------------------------------------------------------------------------
# Notebook view
# ---------------------------------------------------------------------------
def styled_emails(r: Report):
    df = r.emails
    colors = df["_decision"]
    view = df.drop(columns=["_decision", "Draft reply"])

    def paint(col):
        if col.name != "Review status":
            return [""] * len(col)
        return [f"background-color:{DECISION_COLOR.get(k, '')};color:{DECISION_TEXT.get(k, INK)};font-weight:600"
                for k in colors]

    return (view.style.apply(paint).hide(axis="index")
            .set_properties(**{"text-align": "left", "white-space": "pre-wrap"})
            .set_table_styles([{"selector": "th", "props": "text-align:left;background:#f3f2ee;"}]))


def styled_summary(r: Report):
    s = r.summary

    def paint(col):
        if col.name != "Status":
            return [""] * len(col)
        return [f"border-left:6px solid {DECISION_COLOR[k]};font-weight:600" for k in s.index]

    return (s.style.apply(paint).format({"Share": "{:.0%}"}).hide(axis="index")
            .bar(subset=["Emails"], color="#d6e4f7", vmin=0))


def styled_matrix(r: Report):
    m = r.matrix
    return (m.style.format(lambda v: STATUS_LABEL.get(v, "") if isinstance(v, str) else "")
            .map(lambda v: f"background-color:{STATUS_FILL[v]};color:{STATUS_INK[v]};font-weight:600;text-align:center"
                 if isinstance(v, str) else "")
            .set_table_styles([{"selector": "th", "props": "text-align:center;background:#f3f2ee;"}]))


def show(r: Report):
    from IPython.display import Markdown, display
    s = r.summary
    ready = int(s.loc["ready", "Emails"])
    stopped = len(r.results) - ready
    display(Markdown(f"### Order check: {len(r.results)} emails · **{ready} manual-approval candidates** · "
                     f"**{stopped} need attention**"))
    display(styled_summary(r))
    fig = fig_decisions(r); display(fig); plt.close(fig)
    fig = fig_exceptions(r); display(fig); plt.close(fig)
    fig = fig_check_matrix(r); display(fig); plt.close(fig)
    display(Markdown("#### Emails"))
    display(styled_emails(r))


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
def _excel_text(value):
    """Keep untrusted email text as text rather than executable workbook formulas."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def to_excel(r: Report, path: Path | str | None = None) -> Path:
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    path = Path(path) if path else r.output_dir / "order_check_report.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    charts = save_charts(r)

    hex_ = lambda c: c.lstrip("#").upper()
    fill = lambda c: PatternFill("solid", start_color=hex_(c), end_color=hex_(c))
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = fill("#2b2b2a")
    thin = Side(style="thin", color=hex_(GRID))
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    emails = r.emails
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        wb = xw.book

        # --- Summary
        ws = wb.create_sheet("Summary")
        ws.sheet_view.showGridLines = False
        ws["A1"] = "Order email check: summary"
        ws["A1"].font = Font(bold=True, size=16)
        ws["A2"] = f"Created {r.created:%d %b %Y %H:%M}  ·  {len(r.results)} emails  ·  synthetic reference data, no approval or execution implemented"
        ws["A2"].font = Font(color=hex_(INK_2), italic=True)

        ready = int(r.summary.loc["ready", "Emails"])
        kpis = [("Emails checked", len(r.results)), ("Manual-approval candidates", ready),
                ("Need attention", len(r.results) - ready),
                ("Blocked (security)", int(r.summary.loc["blocked", "Emails"]))]
        for i, (label, val) in enumerate(kpis):
            col = 1 + i * 2
            ws.cell(4, col, label).font = Font(color=hex_(INK_2), size=10)
            c = ws.cell(5, col, val)
            c.font = Font(bold=True, size=22)
            c.alignment = Alignment(horizontal="left")

        ws.cell(7, 1, "Review status").font = Font(bold=True, size=12)
        for j, h in enumerate(["Status", "Emails", "Share"], start=1):
            c = ws.cell(8, j, h); c.font, c.fill, c.border = head_font, head_fill, border
        for i, (k, row) in enumerate(r.summary.iterrows(), start=9):
            a = ws.cell(i, 1, row["Status"])
            a.fill, a.font = fill(DECISION_COLOR[k]), Font(bold=True, color=hex_(DECISION_TEXT[k]))
            ws.cell(i, 2, int(row["Emails"]))
            ws.cell(i, 3, float(row["Share"])).number_format = "0%"
            for j in (1, 2, 3):
                ws.cell(i, j).border = border
        tot = 9 + len(r.summary)
        ws.cell(tot, 1, "Total").font = Font(bold=True)
        ws.cell(tot, 2, f"=SUM(B9:B{tot - 1})").font = Font(bold=True)

        ex_row = tot + 2
        ws.cell(ex_row, 1, "Exceptions").font = Font(bold=True, size=12)
        for j, h in enumerate(["Exception", "Emails"], start=1):
            c = ws.cell(ex_row + 1, j, h); c.font, c.fill, c.border = head_font, head_fill, border
        for i, row in enumerate(r.exceptions.itertuples(index=False), start=ex_row + 2):
            ws.cell(i, 1, row.Exception).border = border
            ws.cell(i, 2, int(row.Emails)).border = border

        ws.column_dimensions["A"].width = 28
        for col in "BCDEFGH":
            ws.column_dimensions[col].width = 12

        img = XLImage(str(charts["decisions"])); img.width, img.height = 560, 256
        ws.add_image(img, "J4")
        img = XLImage(str(charts["exceptions"])); scale = 560 / img.width
        img.width, img.height = 560, int(img.height * scale)
        ws.add_image(img, "J20")

        # --- Emails
        view = emails.drop(columns=["_decision"]).apply(lambda column: column.map(_excel_text))
        view.to_excel(xw, sheet_name="Emails", index=False)
        ws = xw.sheets["Emails"]
        widths = {"File": 26, "Received": 10, "From": 32, "Subject": 34, "Review status": 24,
                  "Exceptions": 28, "Why": 50, "Suggestion for reviewer": 45, "Draft reply": 50}
        for j, name in enumerate(view.columns, start=1):
            ws.column_dimensions[get_column_letter(j)].width = widths.get(name, 18)
            c = ws.cell(1, j); c.font, c.fill, c.border = head_font, head_fill, border
        status_col = list(view.columns).index("Review status") + 1
        for i, k in enumerate(emails["_decision"], start=2):
            for j in range(1, len(view.columns) + 1):
                ws.cell(i, j).alignment, ws.cell(i, j).border = wrap, border
            c = ws.cell(i, status_col)
            if k in DECISION_COLOR:
                c.fill, c.font = fill(DECISION_COLOR[k]), Font(bold=True, color=hex_(DECISION_TEXT[k]))
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = ws.dimensions

        # --- Check matrix
        m = r.matrix
        ws = wb.create_sheet("Check matrix")
        ws.cell(1, 1, "Email").font, ws.cell(1, 1).fill = head_font, head_fill
        ws.cell(1, 2, "Review status").font, ws.cell(1, 2).fill = head_font, head_fill
        for j, col in enumerate(m.columns, start=3):
            c = ws.cell(1, j, col)
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(horizontal="center", wrap_text=True, vertical="center")
            ws.column_dimensions[get_column_letter(j)].width = 14
        decision = r.results.set_index("file")["decision"]
        for i, f in enumerate(m.index, start=2):
            ws.cell(i, 1, f).border = border
            k = decision.get(f, "")
            c = ws.cell(i, 2, DECISIONS.get(k, k)); c.border = border
            if k in DECISION_COLOR:
                c.fill, c.font = fill(DECISION_COLOR[k]), Font(bold=True, color=hex_(DECISION_TEXT[k]))
            for j, col in enumerate(m.columns, start=3):
                st = m.at[f, col]
                c = ws.cell(i, j, STATUS_LABEL.get(st, "") if isinstance(st, str) else "")
                c.border, c.alignment = border, Alignment(horizontal="center")
                if isinstance(st, str):
                    c.fill, c.font = fill(STATUS_FILL[st]), Font(bold=True, color=hex_(STATUS_INK[st]))
        ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 28, 24
        ws.row_dimensions[1].height = 32
        ws.freeze_panes = "C2"
        legend_row = len(m) + 3
        ws.cell(legend_row, 1, "Worst result per email and check. Blank = check not run. "
                               "Details per order line are on the 'Check details' sheet.").font = Font(italic=True, color=hex_(INK_2))

        # --- Check details
        det = r.checks.rename(columns={"file": "File", "check": "Check", "status": "Result", "detail": "Detail"}).apply(lambda column: column.map(_excel_text))
        det.to_excel(xw, sheet_name="Check details", index=False)
        ws = xw.sheets["Check details"]
        for j, w in enumerate([26, 42, 10, 70], start=1):
            ws.column_dimensions[get_column_letter(j)].width = w
            c = ws.cell(1, j); c.font, c.fill = head_font, head_fill
        for i, st in enumerate(det["Result"], start=2):
            if st in STATUS_FILL:
                c = ws.cell(i, 3)
                c.fill, c.font = fill(STATUS_FILL[st]), Font(bold=True, color=hex_(STATUS_INK[st]))
            ws.cell(i, 4).alignment = wrap
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions

        # --- Audit log
        ws = wb.create_sheet("Audit log")
        ws.cell(1, 1, "Audit log").font = Font(bold=True)
        for i, line in enumerate(r.audit, start=2):
            ws.cell(i, 1, _excel_text(line))
        ws.column_dimensions["A"].width = 110

        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]
        wb.move_sheet("Summary", offset=-wb.sheetnames.index("Summary"))
        wb.active = 0
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate charts and Excel from existing checker results.")
    parser.add_argument("--input", "--output-dir", dest="input_dir", type=Path, default=OUT, help="Directory containing checker CSV/JSON output")
    parser.add_argument("--output", dest="output_dir", type=Path, help="Write rendered reports here (default: alongside input)")
    args = parser.parse_args()
    rep = load(output_dir=args.input_dir)
    if args.output_dir is not None:
        rep.output_dir = args.output_dir
    charts = save_charts(rep)
    xlsx = to_excel(rep)
    import case_cards
    html = case_cards.write_html(case_cards.load_cases(output_dir=args.input_dir), rep.output_dir / "order_check_cases.html")
    print("Charts:", ", ".join(p.name for p in charts.values()))
    print("Excel: ", xlsx)
    print("Cases: ", html)

