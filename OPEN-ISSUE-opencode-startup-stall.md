# Open issue: OpenCode startup stall in the workshop

**Status: UNRESOLVED as of 2026-09-28.** Referred to someone with deeper Workshop
knowledge. This file is the investigation record so the work is not repeated.

**Nine hypotheses have been proposed and disproven.** Read
[What has been ruled out](#what-has-been-ruled-out) before forming a new one, and
read [Where this investigation went wrong](#where-this-investigation-went-wrong)
before trusting any number in it — several were contaminated by premature kills and
by mistaking short success streaks for fixes.

When resolved, fold the outcome into `AGENTS.md` and delete this file.

---

## Symptom

An `agent` run inside the workshop intermittently stops during initialisation:

- Process alive, ~1–3% CPU, indefinitely. Observed up to 37 minutes without
  recovery.
- OpenCode's log reaches `message=init` and **stops** — no `stream`, no error, no
  further output.
- **No model request is made** — nothing in the host proxy log.
- **No open TCP connections**, no pending I/O (`ss -tnp` shows nothing).
- Nothing written to disk.
- The terminal transcript is empty; OpenCode buffers until it has output.

## How long to wait before calling it hung

This is the most useful operational fact established, and it was established late.

Measured across the 27 runs that reached `stream`:

| Runs | init → stream |
|---|---|
| 26 of 27 | **0.52–0.77s** — tightly clustered, sub-second |
| 1 of 27 (`fb9cf62d`) | **210s**, then ran productively for six minutes |

The normal path is sub-second. A run silent for a minute is already two orders of
magnitude outside it — but recovery after three and a half minutes has happened
once.

**Rule: wait 5 minutes before killing.** That is ~400× the normal window and
comfortably past the only observed slow recovery. Killing at 60 seconds is what
contaminated the failure count below.

Caveat: `fb9cf62d` was on 2026-09-25, before any of the day's configuration
changes. Whether slow recovery is still possible under the current config is
unknown.

## The rate

**17 of 44 runs failed to reach `stream` — 39%.** Roughly constant across the whole
investigation, through every configuration change and every model.

**Treat 39% as an upper bound, not a measurement.** Several of those runs were
killed after 1–3 minutes, inside the window where the one slow recovery would still
have been pending. The true hang rate is lower by an unknown amount.

Recompute cleanly with:

```console
$ workshop exec docs-audit -- sh -c 'grep -oE "run=[a-f0-9]+" ~/.local/share/opencode/log/opencode.log | sort -u | wc -l'
$ workshop exec docs-audit -- sh -c 'grep "message=stream " ~/.local/share/opencode/log/opencode.log | grep -oE "run=[a-f0-9]+" | sort -u | wc -l'
```

## What correlates, weakly

Trivial text-only prompts (`Reply with: ok`) succeed at a much higher rate than
substantive ones. The correlation is **not clean**, and two data points break it:

- A ~400-character prose prompt that invoked tools and read `/inputs` succeeded
  repeatedly.
- A ~130-character pointer prompt (“read this file and follow it”) hung.

So neither length nor “invokes tools” explains it. Something about prompt substance
correlates without being explained by any property yet isolated.

**`prompts/charm-inventory-step0.md` has completed exactly twice** — once on
2026-09-25 (Sonnet 5) and once on 2026-09-28 (DeepSeek). Every other attempt hung.

## Where the evidence lives

Three sources, in order of usefulness:

| Source | Command | Tells you |
|---|---|---|
| OpenCode's own log | `workshop exec docs-audit -- sh -c 'tail -20 ~/.local/share/opencode/log/opencode.log'` | Whether it got past `init` to `stream` |
| Host proxy log | `tail findings/run-logs/proxy.log` | Whether any model request was made (timestamped) |
| Process state | `ps -o pid,etime,time,%cpu -C opencode` | Alive-but-idle vs genuinely working |

A **working** run:

```
message=init
message=stream providerID=openrouter-proxy modelID=...
message="llm runtime selected"
```

A **stalled** run:

```
message=init
                    <- nothing further, ever
```

Historical note: while the catalogue fetch was still failing, stalled runs logged
`Failed to fetch models.dev` between those lines. That is **no longer the
signature** — see hypothesis 5.

## What has been ruled out

Each was proposed, tested, and disproven. Ordered as investigated.

| # | Hypothesis | Disproven by |
|---|---|---|
| 1 | Prompt files carried a header/preamble that confused the model | `git show` proved committed and working-tree prompts byte-identical; the successful 2026-09-25 run used the same file |
| 2 | `opencode.json` `edit` permission lacked a catch-all, so writes auto-rejected | `git diff` showed the first stall ran on the *same config that had just succeeded*. Also: a refused write requires a model call, and no model call is ever made |
| 3 | A non-ASCII em-dash in the prompt broke the `sudo`/`bash` argv chain | Replacing it with `--` still hung |
| 4 | Embedded newlines in the prompt | Flattening to a single line still hung |
| 5 | The unreachable model-catalogue fetch (`https://models.opencode.ai/api.json`) | **The strongest-looking theory, and wrong.** A CONNECT allowlist made the fetch *succeed* — `HTTP 200 in 0.42s` from inside the container, no error logged. It hung anyway, at the same point |
| 5a | — latency variant: the ~10s fetch timeout lost a startup race | Reducing it to 0.57s did not stop the hang |
| 6 | One of the five `opencode.json` options added while investigating (`autoupdate`, `share`, `enabled_providers`, `snapshot`, `small_model`) | Bisected by adding each back individually; all five pass, and the full config completed a substantive 13-charm survey twice |
| 7 | Blocked on some other outbound call | `ss -tnp` shows no TCP connections for a stalled process; the proxy logs no refused CONNECT during the run |
| 8 | Prompt length or delivery method | A 130-char pointer prompt hung; a 400-char prose prompt worked |
| 9 | The model — Anthropic-specific, via the `openai-compatible` adapter | DeepSeek completed two substantive runs, then hung on the third with identical config. Failures span all three models tested |

Verified working independently, so not implicated: the host proxy, the API key
(fingerprint unchanged), model routing (`agent 'Reply with: ok'` works on all three
models), and `opencode.json` reaching the container
(`workshop exec -- cat /project/opencode.json`).

Model IDs were confirmed against OpenRouter's live list (460 models) rather than
assumed — `anthropic/claude-sonnet-5`, `anthropic/claude-opus-5`, and
`deepseek/deepseek-v3.2` are all valid and routable. **Avoid the `:batch` variants**
(`anthropic/claude-opus-5:batch` etc.): those are asynchronous batch endpoints and
would hang an interactive run by design.

## Infrastructure changed along the way — keep it

None of these fixed the stall. Each is a genuine improvement; do not revert them.

### 1. LXD egress `drop` → `reject`

An ACL named `offline` was already applied to `workshopbr0` with
`security.acls.default.egress.action=drop`. `drop` silently discards packets, so
every outbound connection waited for the client's own timeout.

```console
$ lxc network set workshopbr0 security.acls.default.egress.action=reject
```

External connect failure: **15s → 0.04s**. The container stays equally offline.
Asserted by the `check-egress` action, because the setting lives on the host,
outside version control, and reverts silently if the ACL is rebuilt.

### 2. CONNECT allowlist on the host proxy

`openrouter-proxy.py` implements `do_CONNECT`, tunnelling raw TLS bytes to a short
allowlist (`CONNECT_ALLOW`) on port 443 only, so the offline container can reach
exactly the hosts it genuinely needs.

Verified: `models.opencode.ai` returns **HTTP 200 in 0.42s** from inside the
container; `github.com` gets **403**, logged as `CONNECT ... REFUSED`.

It relays encrypted bytes without decrypting, so it needs **no certificate
authority** and cannot read the tunnelled traffic — a dumb pipe, not an
interceptor. Allowlisting is by hostname on the host, which matters because the
catalogue endpoint is CDN-backed and its IPs rotate; an LXD ACL takes CIDRs and
would break silently.

Requires `HTTPS_PROXY=http://127.0.0.1:8317` and `NO_PROXY=127.0.0.1,localhost` in
the `agent` action. OpenCode honours both. `NO_PROXY` keeps model calls direct,
since `opencode.json` already targets the proxy over plain HTTP.

### 3. Timestamped proxy logging

`openrouter-proxy.py` prefixes each logged request with `HH:MM:SS`. Without it,
request lines cannot be attributed to individual runs — which caused a false
conclusion that stalled runs made no model calls at all.

### 4. Removed: `fix-catalogue-fetch`

This action pinned the catalogue host to `127.0.0.1` in the container's
`/etc/hosts`. It **conflicts** with the CONNECT approach — the pin sends the host to
`127.0.0.1:443`, where nothing listens, instead of letting the proxy resolve it.
Deleted from `workshop.yaml`; the entry has been removed from the running
container. Do not reintroduce it.

## Assumptions that were premature

Recorded because each cost time, and because a later reader may be tempted by the
same shortcut.

| Assumption | Reality |
|---|---|
| “`AGENTS.md` says the LXD egress block is available-but-unused” | It had been **active all along** with `action=drop`. One `lxc network get` would have found this hours earlier. This is why the container had no connectivity at all |
| “OpenCode ignores `/etc/hosts`” | It does honour it. The earlier test pinned `models.dev` while the real hostname is `models.opencode.ai` — the wrong name was pinned, and a general conclusion drawn from it |
| “`curl` failing fast proves the fix works” | `curl` uses libc's resolver; OpenCode resolves DNS itself. The `fix-models-dev` action verified itself with `curl` and reported success while the hang was untouched |
| “Zero proxy requests means the run never called the model” | The proxy log had no timestamps at the time, so its 54 request lines could not be attributed to runs. The arithmetic suggested some stalled runs *had* made calls |
| “Runs silent for 60 seconds are hung” | One recovery took **210 seconds**. Several runs were killed prematurely, contaminating the failure count |
| “Two consecutive successes after a change means it is fixed” | At a ~39% failure rate, two passes in a row happen about a third of the time by chance. This caused three separate false “it's fixed” calls in one day |
| “Short prompts work, so prompt size is the variable” | A 130-char prompt hung; a 400-char one worked. The apparent pattern was sampling bias — short prompts were simply run far more often |

## Diagnosing a suspected recurrence

In order, because each step is cheaper than the next:

1. **Is it alive?** `ps -o pid,etime,time,%cpu -C opencode` — minutes elapsed with
   seconds of CPU means idle, not working.
2. **Has it written anything?** `find . -newermt '-10 minutes' -type f`. An empty
   transcript proves nothing; OpenCode buffers.
3. **Did it reach the model?** `tail findings/run-logs/proxy.log`. Timestamped
   requests mean it is working.
4. **Where did it stop?** `workshop exec docs-audit -- sh -c 'tail -20 ~/.local/share/opencode/log/opencode.log'`
   — look for `init` with no following `stream`.
5. **Wait 5 minutes** before concluding. See
   [How long to wait](#how-long-to-wait-before-calling-it-hung).

**Kill with `pkill -f 'opencode run'`.** That matches on the command line, so it
will not touch an unrelated `opencode acp` editor process. Ctrl-C does not reach the
run — it is parented to the container, not your shell. Closing the terminal kills
`tee` and loses the log while the run continues blind.

## Workaround

**Retry.** At ~61% success, a handful of attempts gets a run through. A wrapper is
now worth writing — earlier it was rejected on the belief that substantive prompts
always failed, which the DeepSeek successes disproved.

If automating: **the silence threshold must be 5 minutes, not 60 seconds**, or the
wrapper will kill recoverable runs exactly as this investigation did.

Keep prompts writing durable artifacts regardless. Step 0 of `charm-inventory`
writes `findings/step0-charm-inventory.json` precisely so a halt leaves a record
rather than a lost scrollback.

## Where this investigation went wrong

Nine hypotheses, three false “it's fixed” announcements, and one contaminated
dataset. The causes generalise beyond this bug:

- **Read the failing program's own log before bisecting its inputs.** Four rounds of
  input-bisection (prompt content, em-dash, newlines, length) produced nothing. One
  `tail` of `opencode.log` immediately showed `init` → silence.
- **Compute the base rate before believing a fix.** `grep -c` over the run log takes
  seconds and would have prevented all three false calls. Require enough
  consecutive passes to beat chance.
- **A check must exercise the thing it claims to fix.** The `fix-models-dev` action
  verified itself with `curl` while the hang was in OpenCode — worse than no check,
  because it was reassuring.
- **A correlate is not a cause.** The catalogue fetch appeared in every stalled log.
  Making it succeed changed nothing.
- **Check whether documentation describes the live state.** `AGENTS.md` was wrong
  about the LXD ACL, and that wrong assumption shaped hours of work.
- **Do not kill a slow process to confirm it is stuck.** It destroys the evidence
  and biases the statistics.

## Incidental Workshop findings

Learned the hard way, and worth knowing before writing more actions:

- **Actions do not surface their own `echo` output** — only child process output
  reaches the terminal. Assert via exit status and let the child's message speak.
- **`$(...)` and `; rc=$?` inside an action body fail silently.** Use
  `cmd || test "$?" = "N"`.
- **The agent process outlives your shell.** Parented to the container, so Ctrl-C
  and closing the terminal do not stop it — but closing the terminal *does* kill
  `tee`.
- **`workshop info` and `workshop list` can fail with**
  `timeout waiting for snap system profiles to get updated`. A snapd transient,
  unrelated to the workshop itself; retry.
