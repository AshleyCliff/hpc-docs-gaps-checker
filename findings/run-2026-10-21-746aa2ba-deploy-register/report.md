# Deploy/register consistency — run 2026-10-21-746aa2ba

## Reproducibility

- **Check ID:** `deploy-register`
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

## Unregistered deployed charms (juju-deployed, no charm-table entry)

| ID | Name | Severity | Deploy sites | Register context |
|---|---|---|---|---|
| `deploy-register:ceph-fs:ce0311a7` | `ceph-fs` | missing-entry | `getting-started.md:177` | — |
| `deploy-register:ldap-integrator:0f6525aa` | `ldap-integrator` | missing-entry | `howto/deploy/deploy-identity-provider.md:414` | — |
| `deploy-register:lustre-server:3ee065fc` | `lustre-server` | missing-entry | `explanation/lustre.md:71`; `explanation/lustre.md:78`; `howto/deploy/deploy-lustre.md:33`; `howto/deploy/deploy-lustre.md:70` | — |
| `deploy-register:manual-tls-certificates:c64fdab5` | `manual-tls-certificates` | missing-entry | `howto/deploy/deploy-identity-provider.md:672` | — |
| `deploy-register:microceph:11195f57` | `microceph` | missing-entry | `getting-started.md:172` | — |
| `deploy-register:openssh:244bcf10` | `openssh` | missing-entry | `howto/deploy/deploy-identity-provider.md:840` | — |
| `deploy-register:self-signed-certificates:8febbcbe` | `self-signed-certificates` | missing-entry | `howto/deploy/deploy-identity-provider.md:79` | — |
| `deploy-register:smtp-integrator:cb2c1f23` | `smtp-integrator` | missing-entry | `howto/integrate/integrate-with-email.md:38` | — |

## Skip report

Per `AGENTS.md`'s "report what you skipped" convention: a zero count below is a meaningful result, not an omission.

### Docs side (`doc_claims.py --check deploy-register`)

- `.md` files scanned: **44**
- `.txt` files scanned: **12**
- Deploy instructions found: **47**
- Register entries found: **57**
- Unparseable deploy targets: **0**
- Unrecognised register table rows: **0**
- Unreadable files: **0**
- Excluded by scope: **10**

### Diff (`diff.py --check deploy-register`)

- Register entries (charm tables) with no `juju deploy` instruction anywhere in scope: **6** -- expected and legitimate per spec, not a finding.
  - `alertmanager-k8s`, `catalogue-k8s`, `grafana-k8s`, `loki-k8s`, `mysql-router`, `prometheus-k8s`
