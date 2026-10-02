# Deploy Slurm

This page is a fixture for doc_claims.py tests. It exercises the
word-boundary matching rule from specs/charm-inventory.md.

The `slurmdbd` charm provides database integration. Note that this
mention of "slurmdbd" must NOT register as a mention of "slurmd" --
that is the boundary case the spec calls out explicitly.

Here is a `slurmctld-peer` relation name, which must NOT register as a
mention of "slurmctld" either, since `-` counts as a word character for
boundary purposes.

A deployment command, in a fenced code block:

```
juju deploy slurmctld --channel edge
juju deploy apptainer --channel edge
```

| Charm | Config options |
|---|---|
| sssd | 0 |

## Heading mentioning slurmctld

Prose below the heading above also mentions slurmctld again, in plain
prose context.
