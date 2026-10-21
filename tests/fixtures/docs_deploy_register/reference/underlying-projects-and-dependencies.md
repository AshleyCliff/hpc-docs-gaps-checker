# Underlying projects and dependencies

Fixture for doc_claims.py's `deploy-register` tests, mirroring the real
register page's shape (six csv-table blocks; project tables use bare names,
charm tables use Charmhub links) but with small, synthetic names.

### Core

:::{csv-table}
:header: >
: project, source code, bug report
:widths: 15, 10, 10

widget-charms, [Source](https://github.com/example/widget-charms), [Issue tracker](https://github.com/example/widget-charms/issues)
:::

### Dependencies

:::{csv-table}
:header: >
: project, source code, bug report
:widths: 15, 10, 10

widget-project, [Source](https://github.com/example/widget-project), [Issue tracker](https://github.com/example/widget-project/issues)
:::

### Optional dependencies

:::{csv-table}
:header: >
: project, source code, bug report
:widths: 15, 10, 10

widget-telemetry, [Source](https://github.com/example/widget-telemetry), [Issue tracker](https://github.com/example/widget-telemetry/issues)
:::

### Machine charms

:::{csv-table}
:header: >
: charm, configuration options, actions
:widths: 15, 10, 10

[sssd](https://charmhub.io/sssd)
[echo-server](https://charmhub.io/echo-server), [Options](https://charmhub.io/echo-server/configurations)
:::

### Kubernetes charms

:::{csv-table}
:header: >
: charm, configuration options, actions
:widths: 15, 10, 10

[widget-k8s](https://charmhub.io/widget-k8s), [Options](https://charmhub.io/widget-k8s/configurations)
:::

## Integrations

:::{csv-table}
:header: >
: integration, interface implementation
:widths: 15, 10

sssd, [Implementation](https://github.com/example/widget-charms/blob/main/sssd-interface/README.md)
:::
