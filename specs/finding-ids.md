# Finding IDs

**Status: near-frozen.** Changing how IDs are derived invalidates every
`.driftignore` entry and breaks run-over-run diffing. Treat a change here as a
migration, not an edit.

---

## Why this is settled before the first extractor

Stable, content-derived IDs are the single feature that makes this process
repeatable rather than a one-off. They are what allow `.driftignore` to hold an
accepted finding, run N to be diffed against run N-1 so only *new* findings need
review, and drift to be tracked as a trend. See "Findings" in `AGENTS.md`.

Because the first extractor sets the pattern every later one copies, the
derivation is fixed here rather than discovered per-check.

---

## The rule

```
id = <check>:<subject>:<hash8>
```

Where:

| Part | Meaning | Example |
|---|---|---|
| `<check>` | The check that produced it. Stable string, defined by the check's spec. | `charm-inventory` |
| `<subject>` | The thing the finding is *about*, normalised. Lowercase, `[a-z0-9.-]` only. | `slurmctld` |
| `<hash8>` | First 8 hex chars of `sha256` over the canonical key (below). | `3f9a1c07` |

Example: `charm-inventory:slurmctld:3f9a1c07`

### The canonical key

The hash input is a single UTF-8 string, `\x1f`-separated (unit separator, so no
component can forge a boundary), with exactly these fields in this order:

```
<check>\x1f<kind>\x1f<subject>
```

- `<check>` — as above.
- `<kind>` — the finding class, from the check's own enumerated list
  (e.g. `undocumented-charm`, `phantom-charm`).
- `<subject>` — as above, post-normalisation.

Nothing else is in the hash. In particular:

**Excluded, deliberately:**

| Excluded | Why |
|---|---|
| **Line numbers** | The most important exclusion. A finding must survive unrelated edits above it in the file, or every doc reflow re-opens every accepted finding. |
| **File paths** | A page moved from `howto/x.md` to `howto/deploy/x.md` is the same finding. |
| **Resolved SHAs** | Every ID would change every time a pin moves, making `.driftignore` useless by construction. |
| **Prose, titles, severity** | Reworded output is not a new finding. Severity is derived separately and may be retuned. |
| **Counts and citation lists** | "Mentioned on 3 pages" becoming 4 is not a new finding. |

`file:line` citations are still **required on every finding** — they just live in
the record's body, not in its identity. Identity answers "have I seen this
before"; citations answer "where do I look."

---

## Consequences to accept

These are trade-offs, not oversights.

- **Two findings of the same kind about the same subject collide.** That is
  intended: they *are* the same finding. If a check can legitimately produce two
  distinct findings of one kind for one subject, its `<subject>` is not specific
  enough — fix the subject definition, do not add a disambiguator to the hash.
- **A genuinely different problem about the same subject needs a different
  `<kind>`.** Kinds are therefore part of the contract, and renaming one is an
  ID-breaking change.
- **The hash is redundant with `<check>:<kind>:<subject>`** and adds no entropy —
  it is a fixed-width, filename-safe, greppable handle, and it absorbs future
  key fields without changing the ID's shape.
- **8 hex chars is ~4 billion values.** Collisions across a corpus this size are
  not a practical concern, and a collision is visible (two findings, one ID)
  rather than silent.

## Normalising `<subject>`

Apply in order, so the result is deterministic:

1. Strip surrounding whitespace.
2. Lowercase.
3. Replace any run of characters outside `[a-z0-9.-]` with a single `-`.
4. Strip leading and trailing `-`.
5. If empty after this, the check must fail loudly rather than emit an ID.

Step 5 matters: a silently-empty subject would make every such finding share one
ID.
