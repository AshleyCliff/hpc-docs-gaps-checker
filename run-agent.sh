#!/bin/sh
# Launch an in-container agent run from a committed prompt file.
#
# WHY THIS EXISTS
# ---------------
# The canonical form in AGENTS.md is:
#
#   workshop run docs-audit -- agent "$(cat prompts/<name>.md)" 2>&1 | tee <log>
#
# That is correct for a human at a shell. But some host agents' terminals refuse
# command substitution entirely, so they cannot issue it at all. This wrapper
# does the same thing without `$(...)` in the caller's command line, so the run
# can be driven either by hand or by an agent.
#
# It preserves every property the canonical form earns:
#   - prompt comes from a COMMITTED file, so it can be hashed into a report
#   - whole file passed as ONE argv entry, so no word-splitting
#   - 2>&1 into tee, so permission refusals (stderr) are captured
#   - timestamped log, so runs stay comparable
#   - --foreground + stdin </dev/null, so `workshop run` is not TTY-suspended
#     (observed 2026-09-30: without this it stops with SIGTTIN and never starts)
#
# USAGE
#   ./run-agent.sh prompts/charm-inventory.md
#   ./run-agent.sh prompts/charm-inventory-step0.md 1800

# NOT `set -e`. Observed 2026-10-02: with `set -e`, the moment the pipeline
# below returned non-zero the script exited and `tee`'s output was discarded --
# losing the entire transcript of a run that had already reached the model and
# started Step 0. The log is the artifact; never let a non-zero status destroy
# it. Exit status is captured and reported explicitly instead.
set -u

PROMPT_FILE="${1:?usage: run-agent.sh <prompt-file> [timeout-seconds]}"
TIMEOUT="${2:-3000}"
WS=docs-audit

test -f "$PROMPT_FILE" || { echo "no such prompt file: $PROMPT_FILE" >&2; exit 1; }

BASE=$(basename "$PROMPT_FILE" .md)
STAMP=$(date +%Y%m%d-%H%M%S)
LOG="findings/run-logs/${BASE}-${STAMP}.log"
mkdir -p findings/run-logs

PROMPT=$(cat "$PROMPT_FILE")

echo "prompt: ${PROMPT_FILE}"
echo "log:    ${LOG}"
echo "timeout: ${TIMEOUT}s"
echo

# Run unpiped, writing straight to the log, then show the tail. `tee` is what
# AGENTS.md recommends for a human watching live, but in a wrapper it adds a
# failure mode -- a dead `tee` loses the log while the run continues blind --
# and its exit status masks the real one.
timeout --foreground -k 10 "$TIMEOUT" \
  workshop run "$WS" -- agent "$PROMPT" < /dev/null > "$LOG" 2>&1
RC=$?

echo "--- last 40 lines ---"
tail -40 "$LOG" 2>/dev/null || echo "(log empty)"
echo
echo "exit status: ${RC}"
case "$RC" in
  0)   echo "run completed" ;;
  124) echo "TIMED OUT after ${TIMEOUT}s -- the session may have been working;"
       echo "check the log tail above and whether files were written." ;;
  *)   echo "run exited non-zero; the full transcript is in the log." ;;
esac
echo "saved: ${LOG}"
exit "$RC"
