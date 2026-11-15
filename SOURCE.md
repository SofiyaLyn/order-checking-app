# Source and purpose

This review version builds on SofiyaLyn's **Case-Study-Order-Check** prototype:

https://github.com/SofiyaLyn/Case-Study-Order-Check

Baseline inspected: commit `ba7d698b47f91f7c496284e67e18b18b2be3be42` (13 November 2026).

The original idea, example reference data and reporting structure come from that repository. This version revises the checker, scenario data, report wording and setup, and adds regression tests and a common notebook entry point. It is prepared as a reviewable package for Sofiya. The upstream repository has not been changed.

The original separate mailbox connectors are outside this offline package. Every bundled email is synthetic. Neither this package nor the original prototype executes investment orders.

The complete HTML application adds a local browser interface and Python server around that shared engine. The bundled third-party packages retain their own licenses in vendor/licenses and are listed in vendor/BUNDLED_PACKAGES.json.

