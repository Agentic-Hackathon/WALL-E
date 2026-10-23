# Searchable tool inventory

The console Tool Catalog is generated from actual Python modules with main() and argparse choices. It shows module, description, choices and a copyable command; CLI parsers support `--help`, while services without argparse are explicitly marked SERVICE_NO_HELP. It is not an unrestricted shell. reports/tools_inventory.json captures the detected inventory. Mutating CLI commands are not executed by clicking a catalog entry.

Groups: archive/discovery/data-sync/PIT; feature registry/health/recipe; news/linking/licensing; deep/challenger training and evaluation; patterns; prospective forecasts; portfolio/risk/broker/Shadow; memory/context/advisory; replay/operations; reports and judge preflight. The existing atlas_cli has a single positional command plus shared options: check --help before choosing parameters. Every tool remains subject to its original execution-mode and data guards. LIVE is never a catalog shortcut.

Minimal read-only commands: atlas_cli data-sync-plan, data-sync-status, feature-health, feature-recipe-audit, context-status, operations-report, broker-status; other commands can write research artifacts or fetch public data and require an explicit terminal action. Historical frozen-session CLIs may correctly reject changed source. The console reads saved receipts without resuming them.
