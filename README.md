# Order Check: complete HTML application

This ZIP contains the HTML interface, its Python checker, all core dependency files, synthetic examples and tests.

## Start the app

1. Unzip the entire folder.
2. Double-click **START_WINDOWS.bat** on Windows or **START_MAC.command** on macOS. Linux users can run **START_LINUX.sh**.
3. The app opens in the browser.

**Python 3.10 or newer must already be installed.** No package installation, API key, mailbox connection or internet access is needed for the core app. The small Excel and timezone dependencies are bundled under `vendor`, with their licenses.

Keep the terminal open while using the app. Stop it with Ctrl+C or close that terminal. If the browser does not open automatically, use the local URL printed in the terminal.

A terminal alternative on any platform is:

```text
python launch.py
```

On systems that name Python `python3`, use `python3 launch.py`.

## What works in the HTML interface

- **Demo cases:** run the 18 invented examples, filter or search results, and inspect individual checks and next actions.
- **Try an instruction:** change a synthetic instruction, sender or receipt time and check it immediately with the Python engine.
- **Excel test:** attach a test workbook to a synthetic instruction. A downloadable sample template is available.
- **Local email files:** choose local `.eml` files and review their instructions. Saved authentication headers remain unverified.
- **Export:** save the displayed results as JSON.

All checks run on the computer that starts the app. There is no remote service or trading connection.

## View-only preview

Opening `START_HERE.html` or `index.html` directly displays the bundled results. Search, filtering and case inspection work in that preview. Use the launcher to enable new checks. Browsers cannot start a local Python program merely by opening an HTML file.

## Files

| File or folder | Purpose |
|---|---|
| `index.html`, `app.js`, `styles.css` | Browser interface |
| `demo_cases.js` | Bundled data for the view-only preview |
| `local_app.py` | Local server and JSON endpoints |
| `launch.py`, platform launchers | Startup and bundled-dependency setup |
| `check_orders.py` | The shared validation engine |
| `vendor` | Core Python packages and licenses |
| `tests` | Engine and local-server regression tests |
| `demo` | Synthetic emails and example reports |
| `ENGINE_README.md` | Supported order formats and engine details |
| `INTEGRATION.md` | Connecting an existing HTML page |

## Tests and setup check

```text
python launch.py --check-setup
python run_tests.py
```

The package validation also uses Python's isolated mode with site packages disabled, to check that the bundled libraries are sufficient.

## Demonstration scope

The sender registers, instrument details, balances and cut-off policy are fictional. The trial form simulates authentication. Uploaded email files do not gain trusted authentication from their own headers. Outcomes are recommendations, with independent human controls pending. No approval, order submission or execution action exists.

Unsupported or ambiguous instructions require clarification. The examples are scenario coverage, not a measured production success rate. See `VALIDATION.md`, `CHANGELOG.md` and `SOURCE.md`.

## Adapting Sofiya's HTML

The front end is ordinary HTML, CSS and JavaScript, with no build tool. She can change its design directly or connect an existing page to the documented local endpoints. The Python checker remains the single source of validation logic.
