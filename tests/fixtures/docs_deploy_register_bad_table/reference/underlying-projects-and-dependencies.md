# Underlying projects and dependencies

Fixture for doc_claims.py's `unrecognised_register_table` loud-failure case:
a csv-table block whose nearest heading does not match any of the six known
table identities. Per specs/deploy-register-consistency.md, this must be
counted and surfaced -- never silently dropped, since a dropped table makes
every charm in it look unregistered.

### Mystery charms

:::{csv-table}
:header: >
: charm, configuration options, actions
:widths: 15, 10, 10

[widget-k8s](https://charmhub.io/widget-k8s)
:::
