# Judge quickstart

Install Git and Conda from their official distributions. Obtain read-only access from the organization owner before cloning the private repository (do not share a token in chat). Clone the URL in the root README. Windows/Python 3.12 is the observed environment. Existing host: `conda run --no-capture-output -n shbk python ...`.

For an isolated environment, use `conda create -n wall-e-judge python=3.12` then `conda run -n wall-e-judge python -m pip install -r requirements-m8.txt`. A compatible PyTorch GPU build must be selected using official PyTorch installation instructions for the host driver; CUDA is optional for UI/preflight. Do not upgrade the existing shared shbk environment. Recorded versions are not a universal GPU lockfile. See fresh_clone_test.json for the actual installation attempt, not a promised success.

The actual Windows x64/Python3.12 isolated install succeeded; all89 installed package versions are now recorded in requirements-judge-lock.txt. On that platform use `python -m pip install -r requirements-judge-lock.txt` for the same CPU research stack. `pip check` passed. This is not a claim of GPU bit identity or second-machine financial reproduction. Original archive/weights are still absent in a clean clone.

```powershell
python scripts/judge_preflight.py
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q
python -m wallex_bot.atlas_console --port 8766
python -m wallex_bot.atlas_cli data-sync-plan --top 2 --sync-hours 48
```

Preflight does not request network or orders. Without real archive/checkpoints, numeric integration tests may skip or require local evidence; this is not equivalent to the original host's full run. Do not invent fixtures. Obtain fresh public candles explicitly using `atlas_cli data-sync-run` after inspecting `--help`, then acquire an approved internally generated checkpoint/metadata from the operator. Never download unknown serialized weights as a shortcut. Actual deep inference remains blocked until hashes/recipes match.

Historical M8 status/run/replay/sync-status and m8_evaluation/m8_report CLIs exist; check their `--help`. **Do not run the default frozen M8 session with changed code.** Complete original execution requires checkout of the frozen tag, matching local scripts/archive/weights. Current saved evidence can be inspected read-only by the console. New research requires a fresh directory/manifest and cannot be merged with old prospective evidence.

Stop foreground processes with Ctrl+C. No live adapter is enabled, no autostart installed. Console JSON export uses an allowlist of public research reports; no account credential is exported. The five-minute demo script and rubric reports separate engineering evidence from economic outcomes.
