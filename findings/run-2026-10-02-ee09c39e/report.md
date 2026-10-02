# Charm inventory — run 2026-10-02-ee09c39e

## Reproducibility

- **Check ID:** `charm-inventory`
- **Extractor version:** `1.0.0`
- **Run date (UTC):** `2026-10-02`

| Repo | Resolved SHA |
|---|---|
| `apptainer-operator` | `30441f1bfe0bd8c1ad8c4bdc62e33319ada926a4` |
| `charmed-hpc-libs` | `bb3fbab047556728d3c3b509c8311ec7f7b1d2e4` |
| `charmed-hpc-terraform` | `74094c247541b4eaad16e98e336a79c27bbd39e6` |
| `docs` | `ee09c39e77bc42e830d31427df535e61f7608ef8` |
| `filesystem-charms` | `2db19f2ecbfc7b71b9f8d81956db520f389d8d6c` |
| `slurm-charms` | `cf74cd08109b8e31a251e9152a59093772a31cb2` |
| `slurmutils` | `545c15cbff7ce21dffa95b2d968a5dac29cf5b58` |
| `sssd-operator` | `33ba6eac7ebb43db1b06d184345c20d1618f66e1` |

No model name or prompt hash is recorded: this check is purely deterministic extraction and set operations, with no LLM layer.

## Undocumented charms (in code, not mentioned in docs)

| ID | Name | Severity | Code | Docs |
|---|---|---|---|---|
| `charm-inventory:lustre-server-proxy:d998f828` | `lustre-server-proxy` | missing-entry | `filesystem-charms/charms/lustre-server-proxy/charmcraft.yaml:4` | — |
| `charm-inventory:lustre-server:a720498a` | `lustre-server` | missing-entry | `filesystem-charms/charms/lustre-server/charmcraft.yaml:4` | — |

## Phantom charms (named in docs, no matching charm in code)

None.

## Fixture-suspect charms

Charms whose path contains a `test-` or `-test` segment. Reported separately per spec -- not mixed into undocumented-charm or phantom-charm findings above, because the fixture heuristic is a visibility measure, not a verdict.

| Name | Code | Documented? |
|---|---|---|
| `test-mount-client` | `filesystem-charms/charms/test-mount-client/charmcraft.yaml:4` | no |

## Skip report

Per `AGENTS.md`'s "report what you skipped" convention: a zero count below is a meaningful result, not an omission.

### Code side (`code_facts.py`)

- `charmcraft.yaml` files found: **13**
- Charms emitted: **13**
- Unparseable YAML: **0**
- Missing `name:` key: **0**
- Unreadable files: **0**
- Excluded by scope: **0**

### Docs side (`doc_claims.py`)

- `.md` files scanned: **42**
- Claims emitted: **394**
- Candidate names: **13**
- Unreadable files: **0**
- Excluded by scope: **10**
- Unreliable fence classification: **5**

### Diff (`diff.py`)

- Known-retired charm names loaded: **0**
- Note: no --retired-charms list given; phantom-charm candidate set is empty by design (see spec) (path: `None`)
