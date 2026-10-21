# Deploy orphan-charm again

A second deploy site for `orphan-charm`, in a different file, to exercise the
spec's "A charm deployed in several places yields one finding with several
citations" rule.

```
juju deploy orphan-charm --channel candidate --base ubuntu@26.04
```
