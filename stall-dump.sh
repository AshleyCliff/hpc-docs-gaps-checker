#!/bin/sh
# Capture the internal state of a stalled `opencode run` inside the workshop.
#
# WHY THIS EXISTS
# ---------------
# OPEN-ISSUE-opencode-startup-stall.md eliminated the inputs (h1,3,4,8), the
# network (h5,5a,7), the config (h6) and the model (h9). Every diagnostic used
# so far is EXTERNAL: ps, ss, find, and two log tails. Nothing has yet asked the
# stalled process what it is blocked on. That is the gap this script closes.
#
# READ-ONLY BY CONSTRUCTION
# -------------------------
# By default this only READS: /proc entries, process state, fds, and log tails.
# It never touches /inputs, and it does not kill the run -- deliberately,
# because the issue file's own lesson is "do not kill a slow process to confirm
# it is stuck; it destroys the evidence."
#
# The one destructive step (SIGQUIT) is opt-in via --signal and runs last.
#
# USAGE
#   ./stall-dump.sh                 # dump a currently-stalled run (safe, read-only)
#   ./stall-dump.sh --signal        # ALSO send SIGQUIT (may kill it -- see below)
#
# ON SIGNALS -- READ BEFORE USING --signal
# ----------------------------------------
# `opencode` here is a statically-linked Bun single-file ELF binary (verified:
# v1.18.31, "ELF 64-bit LSB executable ... not stripped"), NOT a node script.
# That matters:
#   * SIGUSR1 does NOT open a debugger port -- that behaviour is Node-specific.
#   * SIGQUIT will most likely TERMINATE it and dump core, rather than printing
#     a JS stack.
# Since the issue file's own lesson is that killing a stalled process destroys
# the evidence, signals are OPT-IN and run LAST, after everything non-
# destructive has already been captured to the transcript.
#
# The binary is "not stripped", so the higher-value route is a real debugger:
# see the gdb section, which runs only if gdb is present and is non-fatal.

set -u

SEND_SIGNAL=0
for a in "$@"; do
  [ "$a" = "--signal" ] && SEND_SIGNAL=1
done

OUT_DIR="findings/run-logs"
STAMP=$(date +%Y%m%d-%H%M%S)
OUT="${OUT_DIR}/stall-dump-${STAMP}.txt"
WS=docs-audit

mkdir -p "$OUT_DIR"

say() { printf '%s\n' "$*" | tee -a "$OUT"; }
hdr() { printf '\n===== %s =====\n' "$*" | tee -a "$OUT"; }

say "stall-dump ${STAMP}"
say "workshop=${WS}"

# ---------------------------------------------------------------------------
# Locate the opencode run process INSIDE the container.
# Match on 'opencode run' so an unrelated `opencode acp` editor process is not
# touched -- same reasoning as the pkill guidance in the issue file.
# ---------------------------------------------------------------------------
hdr "locate opencode run (in container)"
PID=$(workshop exec "$WS" -- sh -c "pgrep -f 'opencode run' | head -1" 2>/dev/null | tr -d '\r\n ')

if [ -z "${PID:-}" ]; then
  say "No 'opencode run' process found inside the workshop."
  say ""
  say "Start a run that is expected to stall, then re-run this script:"
  say "  workshop run docs-audit -- agent \"\$(cat prompts/charm-inventory-step0.md)\" 2>&1 | tee findings/run-logs/step0-${STAMP}.log"
  say ""
  say "Or use --wait to poll for one."
  exit 1
fi
say "pid=${PID}"

# ---------------------------------------------------------------------------
# Is it stalled, or genuinely working? Cheap check first, per the issue file's
# escalation order.
# ---------------------------------------------------------------------------
hdr "process state (alive-but-idle vs working)"
workshop exec "$WS" -- sh -c "ps -o pid,ppid,etime,time,%cpu,stat,wchan:24,args -p ${PID}" 2>&1 | tee -a "$OUT"

hdr "did it reach 'stream'? (init with no stream == stalled)"
workshop exec "$WS" -- sh -c "tail -25 ~/.local/share/opencode/log/opencode.log" 2>&1 | tee -a "$OUT"

hdr "open sockets for this pid (expect NONE if stalled)"
workshop exec "$WS" -- sh -c "ss -tnp 2>/dev/null | grep ${PID} || echo '(no TCP connections -- matches the documented signature)'" 2>&1 | tee -a "$OUT"

# ---------------------------------------------------------------------------
# THE NEW EVIDENCE: what is the process actually blocked on?
# ---------------------------------------------------------------------------
hdr "kernel-side wait channel"
workshop exec "$WS" -- sh -c "cat /proc/${PID}/wchan 2>/dev/null; echo" 2>&1 | tee -a "$OUT"

# VERIFIED 2026-09-29: /proc/<pid>/stack is "Permission denied" in this
# container even under sudo -- normal for an unprivileged LXD container. Kept
# because the error itself is worth recording, but do not expect output.
hdr "kernel stack (EXPECTED TO FAIL here -- unprivileged container)"
workshop exec "$WS" -- sh -c "sudo cat /proc/${PID}/stack 2>&1 || cat /proc/${PID}/stack 2>&1" 2>&1 | tee -a "$OUT"

hdr "per-thread state: what each thread is doing"
workshop exec "$WS" -- sh -c "for t in /proc/${PID}/task/*; do tid=\${t##*/}; printf '\n-- tid %s --\n' \"\$tid\"; printf 'wchan: '; cat \$t/wchan 2>/dev/null; echo; head -4 \$t/status 2>/dev/null | grep -E 'Name|State'; printf 'syscall: '; cat \$t/syscall 2>/dev/null; echo; done" 2>&1 | tee -a "$OUT"

hdr "file descriptors (what is it holding open?)"
workshop exec "$WS" -- sh -c "ls -l /proc/${PID}/fd 2>&1 | head -40" 2>&1 | tee -a "$OUT"

hdr "pending/blocked signals + thread count"
workshop exec "$WS" -- sh -c "grep -E 'Threads|SigQ|SigPnd|SigBlk|State' /proc/${PID}/status" 2>&1 | tee -a "$OUT"

# ---------------------------------------------------------------------------
# Ask the runtime itself for a JS-level stack.
# SIGQUIT / SIGUSR1 are diagnostic for Node-family runtimes and do not
# terminate the process. The JS stack is what external tools cannot see, and
# is the single most likely thing to name the hang.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# The best available route to a USERSPACE stack: gdb against the unstripped
# binary. Non-destructive -- it attaches, dumps, and detaches. This is what
# names the hang if anything does.
# ---------------------------------------------------------------------------
# VERIFIED 2026-09-29: gdb 15.1 is installed (via `workshop run docs-audit --
# apt-install gdb`) and ptrace attach WORKS in this container -- tested against
# a live process, full symbolised backtrace returned, clean detach. Note that
# /proc/<pid>/stack being denied is a SEPARATE restriction and does not imply
# ptrace is blocked.
#
# THIS IS THE MOST VALUABLE SECTION. Everything above is external observation;
# this is the first thing that asks the stalled process what it is waiting on.
# If gdb has gone missing, a `workshop refresh` rebuilt the container -- gdb is
# not persistent. Reinstall and re-run.
hdr "userspace stack via gdb (non-destructive: attach, dump, detach)"
workshop exec "$WS" -- sh -c "command -v gdb >/dev/null 2>&1 || { echo 'gdb ABSENT -- a workshop refresh discards it. Reinstall:'; echo '  workshop run docs-audit -- apt-install gdb'; exit 0; }; sudo gdb -p ${PID} -batch -ex 'set pagination off' -ex 'info threads' -ex 'thread apply all bt full' 2>&1 | head -200" 2>&1 | tee -a "$OUT"

if [ "$SEND_SIGNAL" -eq 1 ]; then
  hdr "SIGQUIT (opt-in; MAY TERMINATE -- Bun binary, not node)"
  say "All non-destructive evidence above is already saved."
  workshop exec "$WS" -- sh -c "kill -QUIT ${PID} 2>&1; sleep 3; echo signal-sent" 2>&1 | tee -a "$OUT"

  say ""
  say "still alive after SIGQUIT?"
  workshop exec "$WS" -- sh -c "ps -o pid,stat,time -p ${PID} 2>&1 || echo 'PROCESS GONE -- itself a finding: it did not handle SIGQUIT'" 2>&1 | tee -a "$OUT"

  hdr "opencode log AFTER signal (a dump may land here)"
  workshop exec "$WS" -- sh -c "tail -60 ~/.local/share/opencode/log/opencode.log" 2>&1 | tee -a "$OUT"
else
  hdr "SIGQUIT skipped"
  say "Not sent. Re-run with --signal to try it, but note it will probably kill"
  say "the process (Bun binary, not node) and end this stall instance."
fi

hdr "any new crash/report files written by the runtime?"
workshop exec "$WS" -- sh -c "find ~ /tmp /project -maxdepth 3 -newermt '-5 minutes' -type f 2>/dev/null | grep -viE '^/project/(findings/run-logs|\.git)/' | head -30" 2>&1 | tee -a "$OUT"

# ---------------------------------------------------------------------------
# Host-side corroboration: did it ever reach the model?
# ---------------------------------------------------------------------------
hdr "host proxy log tail (timestamped == reached the model)"
tail -15 findings/run-logs/proxy.log 2>&1 | tee -a "$OUT"

hdr "clean base rate (recompute; the 39% is a known-contaminated upper bound)"
TOTAL=$(workshop exec "$WS" -- sh -c "grep -oE 'run=[a-f0-9]+' ~/.local/share/opencode/log/opencode.log 2>/dev/null | sort -u | wc -l" 2>/dev/null | tr -d '\r\n ')
STREAMED=$(workshop exec "$WS" -- sh -c "grep 'message=stream ' ~/.local/share/opencode/log/opencode.log 2>/dev/null | grep -oE 'run=[a-f0-9]+' | sort -u | wc -l" 2>/dev/null | tr -d '\r\n ')
say "runs seen:           ${TOTAL:-?}"
say "runs reaching stream: ${STREAMED:-?}"

say ""
say "Saved to ${OUT}"
say "The process was deliberately NOT killed. Kill with: pkill -f 'opencode run'"
