# Open issue: OpenCode startup stall in the workshop

**Status: UNRESOLVED as of 2026-09-28.** Referred to someone with deeper Workshop
knowledge. This file is the investigation record so the work is not repeated.

When it is resolved, fold the outcome into `AGENTS.md` and delete this file.

---

## Symptom

An `agent` run inside the workshop intermittently hangs at startup:

- Process alive, ~0% CPU, indefinitely (observed up to 37 minutes; killed, not
  self-recovered).
- Nothing written to disk — no findings file, no extractor output.
- **Zero requests reach the host proxy**, so no model call is ever attempted.
- The terminal transcript is empty, because OpenCode buffers until it has output.

The same command, config, and prompt sometimes succeed and sometimes hang. Roughly
half the runs on 2026-09-28.

## Where the evidence lives

OpenCode's own log, inside the container, is the only artifact that explains
anything:

```console
$ workshop exec docs-audit -- sh -c 'tail -40 ~/.local/share/opencode/log/opencode.log'
```

A **working** run:

```
message=init
message=stream providerID=openrouter-proxy modelID=anthropic/claude-sonnet-5
message="llm runtime selected"
```

A **stalled** run:

```
message=init
message=ERROR "Failed to fetch models.dev" cause=(GET https://models.opencode.ai/api.json)
message=cleanup prune=7.days        <- and nothing, ever
```

Note the log message says `models.dev` but the URL it actually fetches is
`https://models.opencode.ai/api.json`. Chasing the wrong hostname cost a round of
testing.

## Working theory

OpenCode fetches its model catalogue at startup. The container is deliberately
offline — the model arrives through a Workshop tunnel to a host proxy on
`127.0.0.1:8317` — so that fetch always fails. **OpenCode usually recovers from the
failure and sometimes does not.** Whatever decides that is not visible from
outside.

## What has been ruled out

Each of these was proposed, tested, and **disproven**:

| Hypothesis | Disproven by |
|---|---|
| Prompt file content (header/preamble reaching the model) | `git show` proved committed and working-tree prompts byte-identical; the successful run used the same file |
| `edit` permission lacked a catch-all in `opencode.json` | `git diff` showed the first stall ran on the *same config that had just succeeded* |
| Non-ASCII em-dash in the prompt | Replacing it with `--` still stalled |
| Embedded newlines in the prompt | Flattening the prompt to one line still stalled |
| Prompt length | A ~400-char prose prompt worked; 1343-char stalled; but the same 1343-char file had also succeeded earlier |
| Malformed `opencode.json` | Valid JSON, matches the documented schema, and `workshop exec -- cat /project/opencode.json` confirms the container reads the edited file |
| Proxy down, or stale API key | Proxy up throughout; key fingerprint unchanged; a trivial prompt routes successfully immediately after a stall |
| Model or model ID wrong | `agent 'Reply with exactly: ok'` works instantly, repeatedly |
| Fetch *latency* was the cause | See below — reducing it 9.9s → 0.57s did **not** stop the hang |

## What was tried, and what it achieved

### 1. `opencode.json` options — no effect on the stall

```json
"autoupdate": false,
"share": "disabled",
"enabled_providers": ["openrouter-proxy"],
"snapshot": false,
"small_model": "openrouter-proxy/deepseek/deepseek-v3.2"
```

Each removes a real startup network call or a pointless write, so they are **kept**.
None prevents the catalogue fetch; a run with all of them set still stalled.

### 2. LXD egress `drop` → `reject` — helped latency, did not fix

An ACL named `offline` was already applied to `workshopbr0` with
`security.acls.default.egress.action=drop`. `drop` silently discards packets, so
every outbound connection waits for the client's own timeout.

```console
$ lxc network set workshopbr0 security.acls.default.egress.action=reject
```

Measured effect: external connect failure went from **15s to 0.04s**; OpenCode's
catalogue fetch failure from **9.9s to 3.6s**. Container stays equally offline.

**Worth keeping regardless.** Asserted by the `check-egress` action, because the
setting lives outside the repo and reverts silently if the ACL is rebuilt.

### 3. Pin the catalogue host in the container — helped latency, did not fix

```console
$ workshop run docs-audit -- fix-catalogue-fetch
```

Adds `127.0.0.1 models.opencode.ai models.dev api.models.dev` to the container's
`/etc/hosts`. Fetch failure went from **3.6s to ~0.6s**.

Three consecutive runs then succeeded, which briefly looked like a fix. It was not:
run `8ba36e8f` failed the fetch in **0.57s** and still hung for 10+ minutes. **The
latency theory is disproven.**

### 4. Routing the catalogue fetch through the tunnel — not attempted

The idea is sound: the model calls already work by going to `http://127.0.0.1:8317`,
so the catalogue fetch could take the same path. Two obstacles:

- **Port.** The tunnel is on 8317; the fetch goes to 443. A hosts entry changes the
  address, not the port.
- **TLS.** The fetch is `https://`, so intercepting it means terminating TLS with a
  cert the container trusts — a private CA installed in the container's trust store,
  maintained across rebuilds. That is a lot of machinery for one JSON file, and it
  adds a MITM capability to a container whose security story is "it cannot reach
  anything."

**The question for a Workshop expert:** can that fetch be routed through the
existing tunnel, or the catalogue URL overridden? `strings` on the binary found
nothing (185MB compiled Bun executable, compressed sections), and the published
config docs expose no such option.

## Diagnosing a suspected recurrence

In order, because each step is cheaper than the next:

1. **Is it alive?** `ps -o pid,etime,time,%cpu -C opencode` — a live process with
   minutes elapsed and seconds of CPU is stalled, not slow.
2. **Has it written anything?** `find . -newermt '-10 minutes' -type f`. An empty
   transcript proves nothing; OpenCode buffers.
3. **Did it reach the model?** `tail findings/run-logs/proxy.log`. Timestamped
   requests mean it is working. No requests means it never got past startup.
4. **Why?** `workshop exec docs-audit -- sh -c 'tail -20 ~/.local/share/opencode/log/opencode.log'`
   — look for `init` followed by the fetch failure and no `stream`.

**Kill with** `pkill -f 'opencode run'` — Ctrl-C does not reach it, because the
process is parented to the container rather than your shell. Closing the terminal
kills `tee` and loses the log while the run continues blind.

## Workarounds

- **Retry.** The failure is detectable within ~60s of `init` and costs little to
  re-run. This is the pragmatic path while the issue is open.
- **Keep prompts writing durable artifacts.** Step 0 of `charm-inventory` writes
  `findings/step0-charm-inventory.json` precisely so a halt leaves a record instead
  of a lost scrollback.

## Method notes worth keeping

Five wrong hypotheses preceded "unresolved." Two lessons generalise:

- **Read the failing program's own log before bisecting its inputs.** Four rounds
  of input-bisection produced nothing; one `tail` of `opencode.log` immediately
  showed `init` → fetch failure → nothing.
- **A check must exercise the thing it claims to fix.** An earlier
  `fix-models-dev` action verified itself with `curl`, which honours `/etc/hosts`.
  OpenCode resolves DNS itself, so the action reported success while the hang was
  untouched — worse than no check at all.

Also, incidentally: **Workshop does not surface an action's own `echo` output**
(only child process output), and `$(...)` / `; rc=$?` inside an action body fail
silently. Use `cmd || test "$?" = "N"` and let the child's own message speak.
