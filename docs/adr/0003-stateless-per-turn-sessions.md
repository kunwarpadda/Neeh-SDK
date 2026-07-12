# 0003: Stateless-per-turn model sessions with document-derived delta context, not provider session resume

Date: 2026-07-10
Status: Accepted

## Context

Each Neeh assistant turn invokes the Codex or Claude CLI as a fresh,
ephemeral process (`codex exec --ephemeral`, `claude -p
--no-session-persistence`) rather than resuming a persisted conversation. Two
questions were tested before committing to that as the default: whether
provider-side stateful session resume is cheaper than starting fresh each
turn, and whether sending only what changed since the model's last turn
(rather than the model remembering it, or Neeh resending everything) is
sufficient for correctness.

A stateful session backend was built and probed live (`codex exec resume`,
commit `cd57a6e`). Findings: resumed turns do recall state across turns, but
model configuration must stay identical across the session or the provider's
prompt cache invalidates, and **resumed sessions cannot attach images** —
ruling out session resume for any perception policy that needs a raster.

A follow-up measurement (commit `425e27a`, 19/24 sessions before a manual
stop) found the cost picture is mixed rather than a clear win: a resumed
turn that missed the provider's prefix cache re-billed the *entire* prior
thread as raw input (39k tokens vs. 22.5k for a cold start on a
single-question episode) — worse than starting fresh. When the cache did
hold, uncached input dropped to 4.3k vs. 11.3k (62% cheaper) — but only
about half of resumes actually hit the cache in this test. The resulting
ranking across transports was: **in-turn tool loop > cached resume > cold
resume > stateless two-shot** — the cheapest and most reliable pattern was
not turn-to-turn memory at all, but giving the model more to do *within* one
turn via tool calls, which is the shape the Ink Agent Interface (see
[0001](0001-structured-index-primary-raster-on-demand.md)) already takes.

Separately, a delta-context measurement (commit `12ecf10`, 64/64 clean runs)
tested whether sending only what changed, computed from the document's own
timestamps, preserves correctness while cutting cost: a delta-context window
reached 52% of a full-resend window's size by turn 3, dropping to roughly 17%
by turn 10. A raster-only channel with no such delta mechanism showed an
outright capability loss on state-tracking tasks (0.00 on an erase-detection
task), not merely a cost increase — confirming that the delta needs to be
computed from structure, not inferred from pixels or left to model memory.

## Decision

Model turns stay stateless and ephemeral. Continuity across turns is
provided by Neeh recomputing what changed from the document's own state —
`neeh/agents/assistant.py`'s focus-note mechanism, which compares stroke
authorship and timestamps to identify ink new since the model's last reply —
rather than by provider-side conversation memory.

## Consequences

- No dependency on provider session-resume semantics, and no loss of raster
  attachment for perception policies that need it.
- Cost and correctness both come from the document-derived delta, which is
  deterministic and inspectable, rather than from a cache hit that this
  project's own measurement found held only about half the time.
- This is a measured trade-off from one provider's CLI resume implementation
  at one point in time, not a permanent architectural law. If provider
  session semantics change materially (reliable cache hits, image support
  under resume), or if the in-turn tool loop stops being sufficient as page
  complexity grows, this decision should be re-measured rather than assumed.
