# Charm inventory — run 2026-10-21-746aa2ba

## Reproducibility

- **Check ID:** `charm-inventory`
- **Extractor version:** `1.0.0`
- **Run date (UTC):** `2026-10-21`

| Repo | Resolved SHA |
|---|---|
| `apptainer-operator` | `8f8af3805160c376853ddf2f9039d9af5b793fba` |
| `charmed-hpc-libs` | `238d24f5199f7cf9b0c66bce5944d1f96655b621` |
| `charmed-hpc-terraform` | `74094c247541b4eaad16e98e336a79c27bbd39e6` |
| `docs` | `746aa2baf6922819e35cd9600624cb61bbe8519a` |
| `filesystem-charms` | `7f706b40228a136bad15e6d9528c6942d09ca763` |
| `slurm-charms` | `c80ca6f25b228ac1507e3b703833c0c3639f9b8c` |
| `slurmutils` | `ea29e57a12807d72a2645a669aa8990860bfde7a` |
| `sssd-operator` | `3b944e327fb22bbc5a4c2b15cbcb80359754bc3d` |

No model name or prompt hash is recorded: this check is purely deterministic extraction and set operations, with no LLM layer.

## Undocumented charms (in code, not mentioned in docs)

| ID | Name | Severity | Code | Docs |
|---|---|---|---|---|
| `charm-inventory:lustre-server-proxy:d998f828` | `lustre-server-proxy` | missing-entry | `filesystem-charms/charms/lustre-server-proxy/charmcraft.yaml:4` | — |

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

- `.md` files scanned: **44**
- Claims emitted: **457**
- Candidate names: **13**
- Unreadable files: **0**
- Excluded by scope: **10**
- Unreliable fence classification: **5**

### Diff (`diff.py`)

- Known-retired charm names loaded: **0**
- Note: no --retired-charms list given; phantom-charm candidate set is empty by design (see spec) (path: `None`)
