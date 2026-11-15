# Changes for review

## Complete HTML application

- Added a working browser interface that calls the shared checker through a local Python server.
- Added synthetic instruction editing, Excel test attachments, local email review and JSON export.
- Added Windows, macOS and Linux launchers.
- Bundled the core Excel and timezone packages with their licenses, so the app needs no pip installation or internet access.
- Preserved a view-only HTML preview that works without starting the server.
- Added HTTP integration tests and kept the original engine regression tests.

## Validation and decision logic

- Required failures prevent an instruction from becoming ready for approval.
- Check account existence and account-specific signer rights explicitly.
- Validate quantity, side, workbook structure and populated order lines.
- Send unsupported or conflicting free text to clarification.
- Preserve monetary instructions as amounts rather than inventing unit quantities.
- Assess combined cash and position requirements within the candidate batch.
- Check repeated lines and earlier candidate instructions as possible duplicates.
- Handle receipt times in the configured business timezone. Late orders require review rather than a promise of next-day execution.

## Trust and operational boundaries

- Treat authentication headers in local email files as untrusted by default.
- Allow a clearly labelled simulation only for explicitly marked synthetic fixtures.
- Isolate malformed inputs so one email does not stop the rest of the batch.
- Include order references, reasons and suggested next actions.
- Record run events in an append-only local JSONL log. This is a prototype trace, not a production audit ledger.

## Reporting and use

- Replace invented confidence percentages with descriptive extraction statuses.
- Remove claims that Excel fields are automatically reliable.
- Describe human approval as pending, with no implemented release action.
- Use one engine from the command line and notebook.
- Provide a pre-generated HTML demonstration and regression tests.

See `VALIDATION.md` for the completed checks and `README.md` for setup.

