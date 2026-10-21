# prompts/

Committed prompts for the in-container agent. Versioned so a prompt can be hashed
into a run's report — a CLI string cannot be, which makes an ad-hoc invocation
unreproducible by construction.

## The rule for files in this directory

**A prompt file contains instruction text and nothing else.** No title, no
explanatory preamble, no usage example.

The whole file is passed to the model verbatim by `$(cat ...)`, so anything in it
is read as instruction. An earlier version of these files opened with a heading, a
sentence explaining when to use the prompt, and a fenced block showing the
`workshop run` command — all of which reached the model. `ps` output confirmed it:
the agent's argv began `# Prompt: charm-inventory Step 0 only  A cheap gate-only
run...`.

The fenced command was the worst part, because it referenced the very file being
fed in. Handing a model a shell command that cats its own prompt is a recursion
invitation for no benefit.

So operator-facing notes live **here**, keyed by filename. Prompt files stay pure.

## The prompts

| File | What it does | Cost |
|---|---|---|
| `charm-inventory-step0.md` | Step 0 gate only: verifies the pinned SHAs and the three survey facts, writes `findings/step0-charm-inventory.json`, stops. | cheap |
| `charm-inventory.md` | The full check: Step 0, then implement `code_facts.py`, `doc_claims.py`, `diff.py`, `render.py`, plus tests. | a full session |
| `deploy-register-step0.md` | Step 0 gate only for `deploy-register`: verifies the docs SHA and the register's table shape, writes `findings/step0-deploy-register.json`, stops. | cheap |
| `deploy-register.md` | The full check per `specs/deploy-register-consistency.md`: Step 0, then extend the extractors, plus tests. | a full session |

Use a Step 0 prompt to verify a config change — a permission rule, a model
switch, a moved pin — without paying for an implementation attempt.

### A note on `deploy-register.md`

Unlike `charm-inventory.md`, this prompt asks the agent to **extend** working code
rather than write from scratch. Two consequences worth knowing before a run:

- It must not fork `doc_claims.py` and `diff.py` into parallel per-check copies.
  The prompt leaves the mechanism open (a `--check` selector, or a shared-helper
  module) but requires the agent to state which it chose and why, and requires the
  existing `charm-inventory` tests to still pass. Check both in the final message.
- Run it on **Sonnet 5**, not the cheap model. It looks like imitation work, but it
  introduces a `csv-table` body parser that the later config-options and actions
  checks will inherit — so per the model table in `AGENTS.md` it sets a convention
  rather than copying one.

## Invoking

See "The invocation pattern" in `AGENTS.md` for the canonical form and the reasons
behind each part of it. Short version:

```
workshop run docs-audit -- agent "$(cat prompts/<name>.md)" 2>&1 | tee findings/run-logs/<name>-$(date +%Y%m%d-%H%M%S).log
```

Note that the `agent` process is parented to the container, not your shell: it
survives Ctrl-C and a closed terminal, but `tee` does not. That is why prompts
requiring a durable result tell the agent to write a JSON file rather than only
report conversationally.
