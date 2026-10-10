# Experiments

One folder per run or study: `experiments/YYYY-MM-DD_<module>_<name>/`, containing:
- the config and the exact command used (with the commit hash),
- `results/`: raw outputs (JSON, CSV, logs) exactly as produced,
- `NOTES.md`: what was run, on which data, with which model, and what you observed.

Raw result files are research evidence: commit them and never edit them by hand. If a run was wrong, add a new run and say why in its notes.

Very large files (e.g. full benchmark trajectories) need a team decision on where they go before we commit them.
