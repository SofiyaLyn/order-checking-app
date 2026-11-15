# Complete HTML application validation

Validated on 13 November 2026.

- **111 tests pass:** 86 engine regressions and 25 HTTP integration tests.
- Setup and the full test suite run using Python isolated mode with external site packages disabled: `python -I -S launch.py --check-setup` and `python -I -S run_tests.py`.
- The required Excel and timezone libraries load from the included vendor folder.
- A fresh demo run generates all 18 scenarios and matches every expected disposition.
- HTML, JavaScript and CSS assets are included locally. JavaScript syntax and launcher shell syntax checks pass.
- Live browser testing verified the case list, a new valid instruction, mixed-instruction clarification, and combined status/search filtering.
- The optional chart and Excel report generation completed in the build environment.
- The final archive has been checked for file integrity and executable permissions on the macOS/Linux launchers.

Runtime used: Python 3.12.14 on Linux. Windows and macOS launchers were prepared but not executed on those operating systems. Python 3.10 or newer is required on the recipient's computer. Python itself is not bundled.

The HTML preview works without a server. New checks require the launcher. The application has no mailbox, approval, order-submission or execution connection.

The full test output is in tests/validation_run.txt. Third-party package metadata and licenses are under vendor.
