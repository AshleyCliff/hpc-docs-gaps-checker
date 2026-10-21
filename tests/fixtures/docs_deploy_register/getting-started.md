# Getting started

This page is a fixture for doc_claims.py's `deploy-register` tests. It
exercises every case the spec's "Recognising a deploy instruction" table
calls out explicitly.

First, use `juju deploy`{l=shell} to deploy SSSD in your `slurm` model:

```
juju deploy sssd --base ubuntu@26.04 --channel latest/edge
```

Next, deploy the filesystem pieces. `microceph` needs several flags, split
across lines with a continuation:

```
juju deploy microceph \
  --base ubuntu@26.04 \
  --channel tentacle/stable
```

A locally-built charm, not a Charmhub name, must not be emitted:

```
juju deploy ./local.charm
```

A MyST substitution target must also not be emitted -- it is a hard stop for
that line, not a guess:

```
juju deploy {{ widget_channel }}
```

`widget-project` is a project this fixture's register lists under
Dependencies, but never under either charm table -- the two-namespace rule
means this instruction is still unregistered from a charm-table point of
view:

```
juju deploy widget-project --channel edge
```

`echo-server` is both deployed and correctly registered (see the Machine
charms table below) -- a sanity check that a registered, deployed charm
produces NO finding:

```
juju deploy echo-server --channel edge
```

`orphan-charm` is deployed here, and again in `howto/deploy-echo-again.md` --
appears nowhere in the register at all, so it must yield one finding with
two citations, not two findings:

```
juju deploy orphan-charm --channel edge
```
