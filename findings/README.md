# findings/

The audit's only output. Nothing here is ever read back by the pipeline, and
nothing here crosses into a docs checkout automatically — see the audit boundary
in `AGENTS.md`.

## What is committed, and what is not

| Path | Committed | Why |
|---|---|---|
| `run-<date>-<sha>/findings.json` | **yes** | The durable record. Diffing run N against run N-1 is what makes only *new* findings need review. |
| `run-<date>-<sha>/report.md` | **yes** | The human-readable artifact, with the reproducibility header. |
| `code-facts.json`, `doc-claims.json`, `deltas.json` | no | Intermediates, written flat by the `extract` action and gitignored. |

The intermediates are reproducible from the pinned SHAs in `manifest.lock`, so
committing them adds churn without adding information. The run directory is the
thing worth keeping.

A consequence worth knowing: because the intermediates are overwritten in place,
they describe **the last run only**. Do not read `deltas.json` and assume it
corresponds to the newest `run-` directory unless the run completed.
