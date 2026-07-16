# Ink Event Log v1

Status: experimental SDK protocol. `ink-eventlog/v1` defines the append-only
document event log that makes ink history complete and recoverable. It is not
yet part of stable protocol discovery.

## Principle

Undo/redo is a *mutable* stack: it pops on undo and discards the redo branch on
the next edit, so it cannot answer "what was here before I erased it?". The
event log is the immutable complement. Every mutation that flows through the
editing history -- add, erase, move, restyle, group, page lifecycle, agent
action, undo, redo --
is appended as one `DocumentEvent` and never removed. Because each event carries
the exact strokes it removed and added (strokes are immutable snapshots), erased
and replaced ink stays fully recoverable.

## Event

Each event has:

- `seq`: monotonically increasing sequence number, never reused;
- `event_id`: stable `evt_*` id;
- `kind`: one of `add`, `erase`, `move`, `restyle`, `group`, `page`, `agent`,
  `undo`, `redo` (the finer-grained edit `label` is kept verbatim). Device
  imports map page creation, deletion, and navigation to `kind=page`, preserve
  the original operation in `label`, and retain its descriptor/transition in
  `meta`;
- `page_id` and `at_ms`;
- `removed_ids` / `added_ids`: the strokes actually removed and added at that
  step. Undo records the inverse effect of the edit it reverts; redo re-records
  the original effect.

## Queries

- `replay(to_seq)`: reconstruct the live strokes as of a sequence point,
  including strokes later erased. `to_seq=None` replays the whole log.
- `snapshot(stroke_id, at_seq)`: a stroke's state at a point, or `None` if it
  was not live then.
- `diff(from_seq, to_seq)`: net `added_ids`, `removed_ids`, and `changed_ids`
  (same id, different geometry/style) between two points.
- `recover(stroke_id)`: the last snapshot of a stroke that is no longer live --
  how "restore what I erased" reads ink back out of the log.
- `for_stroke(stroke_id)`: every event that touched a stroke, in order.

## Grouping

Grouping is a relation over strokes, not stroke content, so it lives only in the
log. `Canvas.group(stroke_ids, label=)` appends a `group` event whose `meta`
carries `group_id`, `member_ids`, and an optional `label`; `Canvas.ungroup`
appends a `group` event with `meta.ungroup=true`. Current membership
(`Canvas.groups()` / `EventLog.current_groups()`) is folded from these events in
order, so the full grouping history survives while the current view stays exact.
These are logged but do not enter the stroke undo/redo stacks.

## Persistence

The log serializes two ways. `to_dict()` is the compact, model-facing view (ids
only). `to_snapshot()`/`from_snapshot()` is the full, round-trippable form
including every stroke snapshot, so replay/recover survive a save/load:

- **Internal snapshot:** `Canvas.session_snapshot()` / `save_session()` /
  `load_session()` bundle the document with its event log (`neeh-session/v1`).
- **UIM interchange:** UIM's binary body cannot carry the log, so
  `save_uim(doc, path, event_log=)` writes a `<name>.events.json` sidecar and
  `load_uim_events(path)` reads it back.

## Completeness

`ink-timeline/v1` accepts the log and folds erased/replaced strokes back into
their creation episodes (tagged with `erased_ids`). It claims
`history_complete=true` only when every currently-visible stroke actually passed
through the log; ink added straight to a layer, bypassing the logged editing
API, is honestly reported as incomplete rather than falsely complete.
