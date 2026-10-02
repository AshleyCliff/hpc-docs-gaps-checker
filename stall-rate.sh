#!/bin/sh
# Measure the OpenCode startup-stall rate for a given opencode binary.
#
# WHY A HARNESS AND NOT A FEW MANUAL RUNS
# ---------------------------------------
# The measured failure rate is ~43% (20 of 47 runs). At that rate, two or three
# consecutive passes happen by chance often enough to be meaningless -- which is
# exactly how OPEN-ISSUE-opencode-startup-stall.md records three separate false
# "it's fixed" calls in a single day. Any claim that a change fixed the stall
# needs enough trials to beat chance, so this script runs N attempts and reports
# counts rather than an impression.
#
# Rough guide at a ~43% base rate:
#   5 consecutive passes  ~ 5% by chance   (weak)
#   8 consecutive passes  ~ 1% by chance   (reasonable)
#  10 consecutive passes  ~ 0.4% by chance (strong)
#
# WHAT COUNTS AS SUCCESS
# ----------------------
# Reaching `message=stream` in opencode's own log -- i.e. it got past init and
# called the model. Deliberately NOT "the task completed correctly": this
# measures the stall, not model quality. The log is authoritative here; the
# terminal transcript is not, because OpenCode buffers.
#
# TIMEOUT
# -------
# 5 minutes per attempt, per the issue file: one observed run recovered after
# 210s. A 60s threshold would count recoverable runs as failures and bias the
# result -- the same contamination this measurement exists to avoid.
#
# IMPORTANT: this timeout kills runs that are working perfectly well. Step 0
# does real work (reads /inputs, parses 13 charmcraft.yaml files, writes JSON)
# and takes longer than 5 minutes. That is fine HERE, because the measurement
# is "did it reach the model", which is decided in the first second or two --
# but it means a ~300s elapsed time in the results below is the harness
# stopping a healthy run, NOT a stall. Do not read those timings as latency,
# and do not use this script to judge whether a task completed.
#
# USAGE
#   ./stall-rate.sh <runs> [action] [prompt-file]
#     ./stall-rate.sh 10                                        # long prompt (default)
#     ./stall-rate.sh 10 agent prompts/charm-inventory-step0.md # short gate prompt
#
# The default is deliberately the LONG prompt, because that is the class that
# fails. Measuring the short one produced a misleading 20/20.

set -u

RUNS="${1:-10}"
ACTION="${2:-agent}"
WS=docs-audit

# Hard ceiling per attempt. Normally irrelevant: the poll loop below decides the
# verdict as soon as the run either streams or exceeds STALL_AFTER, then kills
# it. This only backstops a wedged wrapper.
TIMEOUT=420

# How long to wait for `message=stream` before calling it stalled.
#
# The normal init -> stream window is 0.52-0.77s across 26 of 27 measured runs.
# One outlier took 210s and then ran productively, so anything below ~240s risks
# scoring a recoverable run as a stall -- the exact contamination that made the
# original 39% figure unreliable. 300s is ~400x the normal window and clears the
# only observed slow recovery.
STALL_AFTER=300

# Once a run HAS streamed, the stall question is answered and the rest of the
# session is just cost. Kill it after this long rather than paying for a full
# implementation run 10 times over. Set to 0 to let runs complete.
KILL_AFTER_STREAM="${KILL_AFTER_STREAM:-20}"

# WHICH PROMPT YOU MEASURE IS PART OF THE RESULT.
#
# Learned 2026-10-02 the expensive way: 20 consecutive passes were measured with
# the short step0 gate prompt, and the stall then recurred on the first run of
# the long implementation prompt. The streak said nothing about the prompt class
# that actually fails.
#
# Substantive prompts correlate with failure, though no isolated property
# explains it -- a 130-char pointer prompt hung while a 400-char prose prompt
# worked. So measure the prompt you actually intend to run, and state which one
# alongside any rate you quote.
PROMPT_FILE="${3:-prompts/charm-inventory.md}"

STAMP=$(date +%Y%m%d-%H%M%S)
LOG_DIR=findings/run-logs
OUT="${LOG_DIR}/stall-rate-${ACTION}-${STAMP}.txt"
mkdir -p "$LOG_DIR"

say() { printf '%s\n' "$*" | tee -a "$OUT"; }

if [ ! -f "$PROMPT_FILE" ]; then
  echo "missing $PROMPT_FILE" >&2
  exit 1
fi
PROMPT=$(cat "$PROMPT_FILE")

# Baseline of already-streamed run IDs, so we only count runs from this session.
streamed_count() {
  workshop exec "$WS" -- sh -c \
    "grep 'message=stream ' ~/.local/share/opencode/log/opencode.log 2>/dev/null | grep -oE 'run=[a-f0-9]+' | sort -u | wc -l" \
    2>/dev/null | tr -d '\r\n '
}

say "stall-rate ${STAMP}"
say "action=${ACTION}  runs=${RUNS}  timeout=${TIMEOUT}s"
say "prompt=${PROMPT_FILE}"
say "NOTE: a rate is only valid for the prompt it was measured with."
say ""

# Total distinct run IDs in opencode's log, streamed or not. Used to tell
# "opencode ran and stalled" from "opencode never ran".
seen_count() {
  workshop exec "$WS" -- sh -c \
    "grep -oE 'run=[a-f0-9]+' ~/.local/share/opencode/log/opencode.log 2>/dev/null | sort -u | wc -l" \
    2>/dev/null | tr -d '\r\n '
}

PASS=0
FAIL=0
SKIP=0
i=1
while [ "$i" -le "$RUNS" ]; do
  before=$(streamed_count)
  seen_before=$(seen_count)

  # Kill any stragglers so one attempt cannot poison the next.
  workshop exec "$WS" -- sh -c 'sudo pkill -f "opencode run" 2>/dev/null; exit 0' >/dev/null 2>&1

  start=$(date +%s)

  # --foreground and stdin from /dev/null are both load-bearing. Observed
  # 2026-09-30: without them `workshop run` is suspended by a TTY signal
  # (state `Tl`, wchan do_signal_stop) the moment it is launched from a
  # non-interactive script. It then spawns nothing in the container, and
  # because a STOPPED process does not act on SIGTERM until it resumes,
  # plain `timeout` waits in sigsuspend forever -- the batch wedges on
  # attempt 1 with a 0-byte log and no opencode process at all.
  #
  # This looked exactly like the startup stall being investigated and was
  # not: opencode never ran. Distinguish them by checking whether
  # opencode.log was written at all.
  #
  # -k sends SIGKILL 10s after SIGTERM, for anything that ignores TERM.
  timeout --foreground -k 10 "$TIMEOUT" \
    workshop run "$WS" -- "$ACTION" "$PROMPT" \
    > "${LOG_DIR}/attempt-${ACTION}-${STAMP}-${i}.log" 2>&1 < /dev/null &
  wrapper=$!

  # Poll for the verdict rather than waiting for the session to finish. The long
  # prompt runs for many minutes, but the stall is decided within a second or
  # two of init -- so there is no reason to pay for ten full implementation
  # sessions just to learn that they started correctly.
  streamed=0
  while :; do
    sleep 5
    waited=$(( $(date +%s) - start ))

    if [ "$(streamed_count)" -gt "${before:-0}" ]; then
      streamed=1
      # Let it run a little, to confirm it is genuinely progressing and not
      # streaming once then wedging, then stop paying for it.
      [ "$KILL_AFTER_STREAM" -gt 0 ] && sleep "$KILL_AFTER_STREAM"
      break
    fi

    if [ "$waited" -ge "$STALL_AFTER" ]; then
      break
    fi

    # Wrapper died early without streaming -- a crash or refusal, not a stall.
    kill -0 "$wrapper" 2>/dev/null || break
  done

  elapsed=$(( $(date +%s) - start ))

  # Stop this attempt: the verdict is already decided.
  kill -9 "$wrapper" 2>/dev/null || true
  pkill -9 -f "workshop run ${WS}" 2>/dev/null || true
  workshop exec "$WS" -- sh -c 'sudo pkill -9 -f "opencode run" 2>/dev/null; exit 0' >/dev/null 2>&1

  after=$(streamed_count)
  seen_after=$(seen_count)

  if [ "${after:-0}" -gt "${before:-0}" ]; then
    PASS=$((PASS + 1))
    verdict="PASS (reached stream)"
  elif [ "${seen_after:-0}" -le "${seen_before:-0}" ]; then
    SKIP=$((SKIP + 1))
    verdict="INVALID (opencode never started - harness/env fault, not a stall)"
  else
    FAIL=$((FAIL + 1))
    verdict="FAIL (init but no stream after ${STALL_AFTER}s)"
  fi

  say "run ${i}/${RUNS}: ${verdict}  [${elapsed}s]"
  i=$((i + 1))
done

# Clean up the last attempt if it is still hanging.
workshop exec "$WS" -- sh -c 'sudo pkill -f "opencode run" 2>/dev/null; exit 0' >/dev/null 2>&1

say ""
say "=== result for '${ACTION}' ==="
say "passed:  ${PASS}"
say "failed:  ${FAIL}"
say "invalid: ${SKIP}  (opencode never started; excluded from the rate)"
VALID=$((PASS + FAIL))
if [ "$VALID" -gt 0 ]; then
  say "failure rate: $((FAIL * 100 / VALID))%  (of ${VALID} valid attempts)"
else
  say "failure rate: n/a - NO valid attempts. Fix the harness/environment"
  say "before drawing any conclusion about the stall."
fi
say ""
say "Reference: the Bun binary measured 20/47 failures (~43%)."
say "Compare against that, and remember a short pass streak is not a fix."
say ""
say "Saved to ${OUT}"
