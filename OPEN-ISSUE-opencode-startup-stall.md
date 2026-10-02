# Open issue: OpenCode startup stall in the workshop

**Status: STILL OPEN — intermittent, and currently NOT REPRODUCIBLE ON DEMAND.**

Latest data (2026-10-02): the stall recurred once on the long implementation
prompt, then **11 of 11** subsequent runs with that same prompt passed. Combined
with 20/20 on the short prompt over the preceding two days, that is **31 of the
last 32 runs passing**, against a historical 42.6% failure rate.

So the stall is real and still occurring, but rare enough now that there is **no
reproducer** — which is the main obstacle to diagnosing it. See
[Recurrence: 2026-10-02](#recurrence-2026-10-02).

Two cautions for whoever picks this up:

- **Do not call a streak a fix.** That has happened four times here. The 29–30
  September streak was reported as "not reproducing" rather than "fixed" because
  no mechanism was found — and it recurred two days later.
- **Do not call a single stall a regression.** The inverse error. One stall in 32
  runs is consistent with a low-rate intermittent bug, not with a change having
  broken something.

Previously: UNRESOLVED as of 2026-09-28, referred to someone with deeper Workshop
knowledge. This file is the investigation record so the work is not repeated.

**Nine hypotheses have been proposed and disproven.** Read
[What has been ruled out](#what-has-been-ruled-out) before forming a new one, and
read [Where this investigation went wrong](#where-this-investigation-went-wrong)
before trusting any number in it — several were contaminated by premature kills and
by mistaking short success streaks for fixes.

When resolved, fold the outcome into `AGENTS.md` and delete this file.

---

## Recurrence: 2026-10-02

Run `ad641d36`, the first attempt at the full `charm-inventory` implementation
prompt. Stalled identically to the 2026-09-29 specimen.

| Evidence | Value |
|---|---|
| Last log line | `message=init`, 12:50:01 — nothing after |
| `message=stream` for this run | **none** |
| Model call at the proxy | **none** (last was `CONNECT models.opencode.ai` at 08:50:01) |
| Process | alive, `ep_poll`, 10s CPU over 11+ min |
| TCP connections | none |
| Files written | none (only logs) |

Second dump saved: `findings/run-logs/stall-dump-20261002-090142.txt`. Thread
layout matches the first dump exactly — main thread in `ep_poll`, workers in
`futex_do_wait`, nothing to wake it.

### What this recurrence rules out

- **Not the model.** The run used Claude Sonnet 5, switched that morning from
  DeepSeek. But Sonnet 5 appears in **78 successful stream events** historically,
  and the immediately preceding successful run (2026-09-30 14:43) used DeepSeek.
  Consistent with hypothesis 9: failures span all models.
- **Not the proxy allowlist.** The proxy had just been restarted with the correct
  (npmjs-free) allowlist, and the catalogue `CONNECT` succeeded at 08:50:01.
- **Not prompt size per se**, though see the correlation below.

### The prompt-class correlation — tested, and it does NOT hold

The 20 passing runs on 29–30 September all used the **short** gate prompt
(`charm-inventory-step0.md`), while the run that stalled used the **long**
implementation prompt (`charm-inventory.md`). That suggested prompt substance was
the variable, matching the messy pre-existing observation under
[What correlates, weakly](#what-correlates-weakly).

**Tested the same day: 10 further runs with the long prompt, 10/10 passed.**

| Batch | Prompt | Result |
|---|---|---|
| 2026-09-29, 2026-09-30 | step0 (short) | 20/20 pass |
| 2026-10-02 | charm-inventory (long) | 1 stall, then 11/11 pass |

Verified against OpenCode's log: 12 distinct runs on 2026-10-02, 11 streamed, and
the only non-streaming run is the original stall `ad641d36`.

So the long prompt is **not** reliably reproducible either. The stall remains
intermittent and is not explained by prompt class, which is consistent with
hypothesis 8 — neither length nor tool use explains it.

**It also means no reproducer exists.** 31 of the last 32 runs have passed across
both prompt classes, so there is currently no way to trigger the stall on demand
— which is the main obstacle to diagnosing it further.

### Consequence for measurement

`stall-rate.sh` previously defaulted to the step0 prompt, so its 20/20 said
nothing about the long prompt. The default is now the long prompt, with the prompt
file as an explicit third argument, and the script prints a note that a rate is
only valid for the prompt it was measured with.

The harness now also **polls for the verdict and kills the run as soon as it
streams** (default 20s after), rather than paying for a full implementation
session ten times over. Attempts resolve in ~25s instead of ~300s, which makes a
10-run batch cheap enough to repeat.

---

## Confirmation: 20/20 across two days (superseded — see recurrence above)

| Batch | Date | Result | Notes |
|---|---|---|---|
| 1 | 2026-09-29 16:46 | 10/10 passed | Same proxy process throughout |
| 2 | 2026-09-30 09:58 | 10/10 passed | New proxy PID, container up overnight |

Verified against OpenCode's own log rather than the harness's scoring:

| Counter | Before batch 2 | After |
|---|---|---|
| Distinct runs | 57 | 68 (+11: 10 attempts + 1 smoke test) |
| Reached `stream` | 37 | 48 (+11) |
| Runs today reaching `init` but never `stream` | — | **0** |

The 20 historical failures all pre-date 2026-09-29 and are unchanged.

**Probability of 20 consecutive passes at a 42.6% failure rate: ~0.002%.** The
stall is not occurring under the current configuration.

**Why this still says "not reproducing" and not "fixed":** no mechanism was ever
found. Nothing in the day's changes has a plausible causal link to an idle Bun
event loop, so a latent timing-dependent bug cannot be excluded. Per this file's
own history — three false "it's fixed" calls in one day — the bar is a mechanism
or sustained absence, not a streak.

### A harness fault that mimicked the stall exactly

Worth recording, because it nearly produced a false *negative* as convincing as
those three false positives.

Batch 2's first attempt wedged for 38 minutes. The symptoms were indistinguishable
from the stall: no output, no model call, process alive, nothing written. The cause
was entirely different:

```
timeout 300 workshop run …   S   sigsuspend      <- waiting on child
workshop run docs-audit …    Tl  do_signal_stop  <- STOPPED
```

`workshop run`, launched from a non-interactive script, was suspended by a TTY
signal (`SIGTTIN`/`SIGTTOU`) before spawning anything in the container. Because a
**stopped process does not act on SIGTERM until it resumes**, `timeout` waited
forever. OpenCode never ran at all — `opencode.log` was untouched.

Fixes in `stall-rate.sh`:

- `timeout --foreground -k 10` and stdin from `/dev/null`, which prevents the
  suspension; smoke-tested with a trivial prompt.
- A third verdict, **`INVALID`**, for attempts where OpenCode's *total* run count
  did not move. Those are excluded from the rate, because they say nothing about
  the stall.
- With zero valid attempts the script refuses to compute a rate at all.

**The distinguishing check: did `opencode.log` get written?** If not, OpenCode
never started and it is an environment fault, not a stall. Anyone diagnosing a
recurrence should apply that test first.

---

## The 2026-09-29 session

Four things were established. The first is the headline; the rest are why it is
not yet a closed case.

### 1. A clean 10-run measurement passed 10/10

`./stall-rate.sh 10 agent` — 10 attempts, `prompts/charm-inventory-step0.md`,
counting "reached `message=stream`" from OpenCode's own log. Cross-checked three
ways rather than trusted:

| Check | Before | After |
|---|---|---|
| Distinct runs in `opencode.log` | 47 | 57 |
| Runs reaching `stream` | 27 | 37 |
| Model calls at the proxy, test window | — | 225 |

Ten runs, ten new streams, and real model traffic. **The prior rate was 20/47
failures (~43%); ten consecutive passes at that rate is ~0.4% by chance.**

Caveat that matters: this does not identify a *mechanism*. Nothing in the day's
changes has an obvious causal link to an idle Bun event loop, so a latent
timing-dependent bug remains plausible. Treat as strong evidence, not a diagnosis.

**A run also completed Step 0 end to end**, rewriting
`findings/step0-charm-inventory.json` with valid JSON: `halted: false`,
`shas_match_lock: true`, all three survey facts confirmed, and all 13 charms with
correct `name:` values — including the `apptainer` and `sssd` cases where the
declared name differs from the directory. Before this session the issue file
recorded Step 0 completing exactly twice ever. This is stronger than "reached the
model": the agent did the work, obeyed the read-only constraint, and produced its
durable artifact.

### 2. The stall is an idle event loop, not a deadlock

First dump taken from *inside* a live stall (`findings/run-logs/stall-dump-*.txt`),
via `gdb` attach. All 14 threads in benign waits:

| Thread | State |
|---|---|
| `opencode` (main) | `ep_poll` |
| `HTTP Client` | `ep_poll`, **no socket open** |
| `IO Watcher` | `ep_poll` |
| 7× `HeapHelper` | `pthread_cond_timedwait` |
| 3× `Bun Pool` | `futex_do_wait` |

No mutex contention, no futex deadlock, `SigPnd: 0`, 7s CPU over 8 minutes. The
process is a correctly-functioning event loop **with nothing left to wake it**.
This rules out the whole lock-cycle / blocked-syscall class and points to a lost
wakeup or unresolved promise between config load and provider construction.

Limitation: backtraces are `?? ()` — `gdb` cannot resolve Bun's JIT frames, so
thread states are known but the JS call site is not.

### 3. OpenCode has NO Node build — do not re-propose this

The obvious hypothesis ("run it on Node instead of Bun") **is not testable.** The
npm package `opencode-ai` downloads the same Bun-compiled ELF executable
(`bin/opencode.exe`, 185 MB) and wraps it; Node is never involved at runtime.

| | SDK binary | npm 1.18.33 |
|---|---|---|
| SHA256 | `f9dab322…` | `0abbb7c3…` |
| BuildID | `c30f169b…` | `c30f169b…` |
| Type | Bun ELF | Bun ELF |

Different builds, same runtime. An npm install version-compares two Bun binaries
and nothing more. `workshop.yaml` carries a note so this is not retried.

### 4. Infrastructure fixed along the way

- **`gdb` works.** `ptrace` attach succeeds in the container. Note that
  `/proc/<pid>/stack` being denied under `sudo` is a *separate* restriction and
  does **not** imply `ptrace` is blocked — that inference was made and was wrong.
- **A plain-HTTP proxy path exists** for apt (`HTTP_ALLOW` in
  `openrouter-proxy.py`, `apt-install` in `workshop.yaml`), so the offline
  container can install packages without a new hole in the LXD egress block.
  Model calls and apt are dispatched *before* key injection, so no third-party
  host ever sees the API key — verified with a sentinel key.
- **Chunked encoding hangs apt.** The first version of that path served every
  response `Transfer-Encoding: chunked`; apt's `http` method wants
  length-delimited bodies and wedged indefinitely — `apt-get`, `store` and `gpgv`
  all parked in `poll()` with zero CPU and nothing written. Fixed by buffering and
  sending an explicit `Content-Length`. **A single non-pipelined GET test passed
  against the broken version**, which is the "a check must exercise the thing it
  claims to fix" lesson repeating itself.

### What would confirm or refute the fix

1. ~~**Another 10 runs**, ideally on a different day.~~ **Done 2026-09-30: 10/10.**
   See [Confirmation: 20/20](#confirmation-2020-across-two-days).
2. **A mechanism.** Still unknown. This is why the status is "not reproducing"
   rather than "fixed".
3. **The host comparison**, still unrun: `opencode` on the host, unproxied,
   direct to OpenRouter. Lower value now that the container path is passing —
   keep it in reserve for a recurrence.

**Do not delete this file yet.** Two things are worth keeping even though the
stall is not reproducing: the diagnostic runbook, which is the fastest route back
to the evidence if it returns, and the harness-fault distinction above, which is a
live trap for anyone measuring this. Delete only once a mechanism is known, or
after a sustained period of normal use with no recurrence.

### If it recurs

In order:

1. **Was `opencode.log` written?** If not, OpenCode never started — environment
   fault, not the stall. See the harness note above.
2. **`init` with no `stream`?** That is the stall. Do not kill it.
3. **Dump it:** `./stall-dump.sh` — `gdb` is installed and `ptrace` works, so this
   captures thread states and a backtrace. Non-destructive.
4. **Re-measure:** `./stall-rate.sh 10 agent` for a rate rather than an anecdote.

### A harness caveat worth knowing

`stall-rate.sh` caps each attempt at 5 minutes. Step 0 does real work and takes
**longer** than that, so a ~300s elapsed time in its output is the harness stopping
a *healthy* run, not a stall. The pass/fail verdict is still correct — it keys on
reaching `stream`, decided in the first second — but those timings are not latency
and the script must not be used to judge task completion.

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

**Historical: 17 of 44 runs failed to reach `stream` — 39%.** Roughly constant
across the whole investigation, through every configuration change and every model.

**Recomputed 2026-09-29, before that day's fixes: 20 of 47 — 42.6%.** Note this is
*higher* than the 39% figure it replaces, so the concern that premature kills had
inflated the number turned out not to matter much. The rate was real and stable.

**Then 10 of 10 passed** after the day's changes — see
[The 2026-09-29 session](#the-2026-09-29-session). Any future comparison should
use 42.6% as the pre-fix baseline, not 39%.

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

**Possibly unnecessary now** — see [The 2026-09-29 session](#the-2026-09-29-session),
where 10 of 10 runs passed. Keep this section until that is confirmed.

**Retry.** At the pre-fix ~57% success rate, a handful of attempts gets a run
through. `stall-rate.sh` already implements the retry-and-count loop and can serve
as the basis for a wrapper; earlier a wrapper was rejected on the belief that
substantive prompts always failed, which the DeepSeek successes disproved.

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
