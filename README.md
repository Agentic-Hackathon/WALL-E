# WALL-E — Wallex Atlas

Private competition research submission. [فارسی](README_FA.md) · [Judge quickstart](docs/JUDGE_QUICKSTART_EN.md) · [Architecture](docs/ARCHITECTURE_FA.md).

**SHADOW ONLY / LIVE HARD_DISABLED. No verified economic edge.** Original Champion, RiskGate, checkpoints and historical sessions are preserved. This release does not authorize real orders. Deadline: **2026-10-23 23:50 Asia/Tehran = 20:20 UTC**. Entries stop an hour earlier; the deadline controller cannot guarantee fills.

```powershell
git clone https://github.com/Agentic-Hackathon/WALL-E.git
cd WALL-E
python scripts/judge_preflight.py
python -m wallex_bot.atlas_console --port 8766
```

The console is local, read-only and never loads keys from files. Missing archive/checkpoints are shown as `DATA_NOT_AVAILABLE`; clean source delivery is not delivery of private state or model weights. Use the documented isolated environment for research. A clean clone is not an exact reproduction of the original M8 workspace; its source contract includes historical local inputs. Do not resume old frozen sessions with this changed source. Use the original tag/checkout and matching local assets for historical execution, or create a new research session with its own tracked manifest.

See [limitations/results](docs/LIMITATIONS_AND_RESULTS.md), [licenses](docs/THIRD_PARTY_ATTRIBUTION.md), [model card](docs/MODEL_CARD.md), [decision trace](docs/DECISION_TRACE.md), [deadline](docs/TRADING_DEADLINE_1405_08_01_FA.md). FinBERT NC weights are not bundled or enabled for competition decisions. No score or profit from external READMEs is an Atlas result.
