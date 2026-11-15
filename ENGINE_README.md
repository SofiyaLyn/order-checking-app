# Order Check: improved interview prototype

An offline review version of Sofiya's investment-order email checker. It demonstrates instruction extraction, pre-order checks and exception routing with synthetic data.

**Start by opening `START_HERE.html`.** The packaged report needs no installation or internet connection. It contains scenario results, checks and proposed next actions.

## Run the demonstration

Use Python 3.10 or later. From this folder:

```text
python -m venv .venv
```

Activate the environment:

```text
Windows:        .venv\Scripts\activate
macOS / Linux:  source .venv/bin/activate
```

Then run:

```text
python -m pip install -r requirements.txt
python run_demo.py
```

Reopen `START_HERE.html` to see refreshed results. The demo generates its own sample emails.

The `demo/output` folder contains the HTML report, `results.csv`, `checks.csv`, `cases.json`, an append-only JSONL trace and a readable log. `run_console.txt` captures the latest demo's console output.

## Run the tests

```text
python -m unittest discover -s tests -v
```

These regression tests exercise original failure cases and malformed, ambiguous and repeated instructions. `VALIDATION.md` records the checks performed on this package.

## Check a local folder without simulating trust

```text
python check_orders.py --input path/to/local_eml_files --output output
```

This command reads files only. A saved email cannot establish the provenance of its authentication headers or a trusted receipt timestamp. The normal file path therefore does not mark an instruction ready on that evidence alone. A future approved intake adapter would need to supply trusted metadata.

`--demo-auth` simulates authentication and receipt checks only for generated fixtures carrying `X-Order-Check-Demo: synthetic-v2`. Results label the simulation. The marker is not a security credential.

## Supported instructions

The parser accepts a narrow format. A typical unit instruction is:

```text
Please buy 100 units of IE00WRLD0013 for account 100234.
```

A monetary instruction stays an amount:

```text
Please buy EUR 25,000 of IE00WRLD0013 for account 100234.
```

It does not turn EUR 25,000 into units at an indicative reference price. Unsupported wording, conflicting terms, an inferred account, a correction or a cancellation needs review or clarification. Free-text numbers use comma thousands separators and a dot for decimal amounts, for example `25,000.50`. Whole-unit instructions use integer notation. Space-separated, apostrophe, scientific or fractional size formats require review rather than partial extraction.

Excel templates use `Account`, `Side`, `ISIN` and `Units` (or `Amount`), with optional `Currency`. Their contents still require validation. Formula cells, malformed workbooks, empty orders, invalid directions and unsupported quantities cannot pass as complete instructions. This demonstration supports positive whole units and EUR balances.

Instrument data, balances, signer registers and policy choices are sample data. The cut-off and timezone illustrate configurable rules and do not describe Erste's actual rules.

## Status meanings

| Status | Meaning |
|---|---|
| Candidate for manual approval | A supported candidate passed the configured sample checks. Independent human controls and approval remain pending. |
| Human review | Required evidence or interpretation needs clarification or judgment. |
| Rejected | A required business or input check failed. Correct and reassess. |
| Blocked | A sender or authorization concern prevents processing. Verify through an established channel. |
| Held: possible duplicate | A repeated instruction needs confirmation. Legitimate identical second orders remain possible. |

The report recommends a disposition. It does not implement reviewer sign-off, OMS release or execution.

## Notebook and optional reporting

`Demo.ipynb` uses the same engine as `run_demo.py`. Open the HTML report in a browser for filtering.

The charts and Excel report are optional:

```text
python -m pip install -r requirements-report.txt
python report.py --input demo/output
```

## Scope

- No live mailbox, external API, client-data upload or trading connection.
- No AI model and no calibrated confidence scores. Extraction statuses describe the parser's evidence.
- Cash and holdings checks use sample snapshots and conservative reservations for candidate orders. They do not replace live balances or an OMS.
- Duplicate checks cover the supplied batch and its candidate history. There is no durable cross-run order ledger or partner idempotency service.
- The local trace remains editable by its owner. Production audit retention, access controls and tamper evidence remain design work.
- Partner acknowledgments, owned exception queues, escalation timers and amendments after submission belong in the wider operating model.

## Suggested interview use

Allow 60-90 seconds. Show one complete instruction and one ambiguous or duplicate instruction. Explain the outcome and what Operations must do next. These examples demonstrate scenario coverage, not measured fraud detection, automation rates or production capacity.

See `CHANGELOG.md` for changes and `SOURCE.md` for attribution to Sofiya's repository.

