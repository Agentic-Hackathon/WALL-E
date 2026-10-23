# Two distinct reproduction contracts

1. Historical M8 execution: frozen a112709 and original local source manifest, archive, private checkpoints and helper scripts. Historical source hashes/forward sessions are immutable. Check out a separate copy/tag; do not overwrite the current workspace or merge new evidence into the old session.
2. Fresh research clone: scripts/judge_preflight.py manifests only Git-tracked source, scripts and requirements, LF-normalized SHA256. The two untracked historical helper scripts are excluded. This new manifest is independent and does not pretend to validate or repair the historical contract. Fresh public data and approved training/checkpoints produce a new experiment, not the old results.

Run preflight in both original and fresh clone and compare tracked source manifest after committing. Reports/models absent => DATA_NOT_AVAILABLE, never a fabricated score. requirements-m8.txt records the observed stack; isolated installation outcome is reported separately. CUDA numerical bit identity and fresh-machine success are not presumed. All runtime source changes are committed; tests disable pytest plugin autoload in the shared host.
