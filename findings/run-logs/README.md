# run-logs/

Terminal transcripts from `workshop run` invocations, plus `proxy.log` from
`openrouter-proxy.py`. **Gitignored** except this file.

The two are meant to be read **together**: an agent transcript is buffered and may
show nothing, while `proxy.log` timestamps every model request and so acts as a
heartbeat. Requests still arriving means the agent is working and merely silent;
requests stopping mid-run means the stall is upstream of the model. That comparison
is the only tool available for [the unexplained stall](../../AGENTS.md).

`proxy.log` is appended across sessions on purpose — its value is comparing runs,
not inspecting one. Each startup line carries the key fingerprint, which is where
one session ends and the next begins.

## Why these are not committed

A log is the model *narrating* what it did. `findings/run-<date>-<sha>/` and
`findings/step0-*.json` are what it actually *produced*. When the two disagree,
believe the structured output.

Logs are kept because they are the only place some things appear:

- Permission refusals (`external_directory` auto-rejects, and similar).
- The tool-call sequence leading to a halt.
- Crashes and stack traces.
- Token and cost accounting, when OpenCode emits it.

None of that belongs in the findings record, and all of it is useful when
diagnosing a run that went wrong.

## Retention

Disposable. Delete freely — nothing in the pipeline reads them. If a log contains
something worth keeping, the right move is to fix the extractor or the spec so the
fact lands in `findings/` instead.
