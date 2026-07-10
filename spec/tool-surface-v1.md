# Neeh Tool Surface v1

Protocol identifier: `neeh-tools/v1`

Status: Phase 1 core surface. The eleven tools in [Core tools](#core-tools) are shipped by the
Python reference library. Batching, read pagination, and the event cursor are specified extension
points and are not currently advertised.

This specification defines the JSON contract between a Neeh canvas host and a script, test
harness, MCP binding, or agent runtime. It is transport-neutral: an MCP server, local RPC bridge,
or in-process adapter can expose the same names and schemas.

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are normative requirements.

## Discovery and versioning

Python callers discover this exact protocol with:

```python
from neeh.protocol import protocol_versions
from neeh.tools import tool_manifest

assert protocol_versions()["tool_surface"] == "neeh-tools/v1"
manifest = tool_manifest()
# {"protocol": "neeh-tools/v1", "tools": [...]}
```

Each `tools` entry contains `name`, `description`, and `input_schema`. The manifest is
authoritative: a host MUST NOT accept a reserved tool unless it advertises that tool and its
schema. Protocol versions and Python package versions are independent; see
[Versioning](../ARCHITECTURE.md#versioning).

A remote binding MAY extend its discovery response with a `capabilities` object, but MUST retain
the `protocol` and `tools` members. Extension capability names defined here are
`batch_requests`, `read_pagination`, and `event_cursor`.

When a remote binding advertises extensions, it uses this shape (numbers shown are examples):

```json
{
  "protocol": "neeh-tools/v1",
  "tools": [],
  "capabilities": {
    "batch_requests": {"supported": true, "atomic": true, "max_requests": 64},
    "read_pagination": {"supported": true, "default_limit": 100, "max_limit": 1000},
    "event_cursor": {"supported": false}
  },
  "limits": {
    "max_request_bytes": 1048576,
    "max_result_bytes": 16777216,
    "max_add_stroke_points": 10000,
    "max_id_filter_items": 1000,
    "max_write_text_utf8_bytes": 16384
  }
}
```

All advertised maxima MUST be positive integers and are hard limits. Byte limits count the UTF-8
JSON envelope, including base64 render data. `max_id_filter_items` applies to every `stroke_ids`
argument. A capability with `supported=false` MUST NOT change a core tool schema.

## Common wire contract

One transport request identifies a tool and supplies one JSON object of arguments:

```json
{
  "request_id": "req_01J...",
  "tool": "get_strokes",
  "arguments": {"author": "user"}
}
```

`request_id` is OPTIONAL but, when supplied, MUST be copied to the response. A transport MUST
validate the advertised input schema before executing a tool and MUST reject unknown arguments.

A successful transport call has this envelope:

```json
{
  "ok": true,
  "result": {},
  "request_id": "req_01J..."
}
```

A failed transport call has this envelope:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_argument",
    "message": "region is inverted",
    "details": {"argument": "region"},
    "retryable": false
  },
  "request_id": "req_01J..."
}
```

Exactly one of `result` or `error` is present. `details` MUST be a JSON object and MUST NOT expose
stack traces, filesystem paths, credentials, or provider internals. `retryable` says whether
retrying unchanged input could reasonably succeed.

The in-process Python API is intentionally thinner: `call_tool(canvas, name, arguments)` returns
the tool's result object directly and maps failures to Python exceptions. A binding maps those
exceptions to the wire errors below; it does not wrap in-process success values.

### Error codes

| Code | Meaning | Default `retryable` |
|---|---|---:|
| `invalid_request` | Malformed envelope or non-object arguments. | false |
| `unknown_tool` | Name is absent from the advertised manifest. | false |
| `invalid_argument` | Schema, coordinate, time, enum, or cross-field validation failed. | false |
| `limit_exceeded` | Request or response would exceed an advertised host limit. | false |
| `cursor_invalid` | Cursor is malformed, belongs to another query/page, or was tampered with. | false |
| `cursor_expired` | Cursor's retained snapshot or event history is no longer available. | false |
| `layer_locked` | The requested mutation targets a locked layer. | false |
| `conflict` | State changed so the operation cannot be applied consistently. | true |
| `capability_unavailable` | A reserved style, tool, renderer, or extension is not enabled. | false |
| `render_unavailable` | Requested renderer or optional dependency is unavailable. | false |
| `batch_failed` | An advertised atomic batch failed and was rolled back. | false |
| `internal_error` | Unexpected host failure. | true |

Bindings SHOULD preserve a safe diagnostic in `message` and put machine-actionable facts such as
`argument`, `max`, `restart_cursor`, or `current_revision` in `details`.

## Common values and invariants

- A region is `[min_x, min_y, max_x, max_y]` in current-page coordinates. Values MUST be finite,
  `min_x <= max_x`, and `min_y <= max_y`. Zero-area regions are valid.
- A point is `[x, y]` or `[x, y, t_ms, pressure, tilt_x, tilt_y]`. Omitted values default to
  `t_ms=0`, `pressure=1`, `tilt_x=0`, and `tilt_y=0`. Producers SHOULD send either two or all six
  values; intermediate tuple lengths are accepted for compatibility and fill trailing defaults.
- `t_ms` is a non-negative integer stroke-relative offset. Pressure is in `[0, 1]`; each W3C tilt
  value is in `[-90, 90]`. Point times MUST be non-decreasing.
- Stroke, layer, page, and request IDs are opaque non-empty strings. Moving or restyling a stroke
  MUST preserve its stroke ID.
- Agent-created ink MUST have `author=agent` and MUST land on the current page's agent layer. A
  tool MUST NOT silently add agent ink to a user layer or relabel user ink as agent ink.
- Locked layers MUST NOT be mutated. Erase and move MAY skip locked targets, but MUST NOT report a
  skipped target as changed.
- Every successful mutating call is atomic and creates at most one undo-history entry. This
  includes `write_text`, even when it creates many strokes. A failed call MUST leave document,
  selection, and history state unchanged.
- A new successful edit clears redo history. `undo` and `redo` replay an already-validated edit
  even if a layer was locked after the original edit.
- Region selection, erase, and vector filtering use stroke bounding-box intersection in v1, not
  point-accurate hit testing.

## Core tools

The v1 core contains exactly these names:

| Tool | Required arguments | Optional arguments | Result |
|---|---|---|---|
| `view_page` | — | `format: svg\|png` (default `svg`) | `{page_id,width,height,format,data}` |
| `view_region` | `region` | `format: svg\|png` (default `svg`) | `{page_id,region,format,data}` |
| `get_strokes` | — | `region`, `stroke_ids`, `author`, `since_ms`, `visible_only`, `include_points` | `{page_id,width,height,region,stroke_count,strokes}` |
| `add_stroke` | `points` | `color`, `width`, `brush` | `{stroke_id,bbox}` |
| `erase` | at least one of `stroke_ids`, `region` | — | `{erased}` |
| `select` | — | `stroke_ids`, `region` | `{selected,bounds}` |
| `move` | `dx`, `dy` | `stroke_ids` (default current selection) | `{moved}` |
| `highlight` | `region` | `color` | `{stroke_id,region}` |
| `write_text` | `text`, `region` | `style`, `color`, `size` | `{stroke_ids,size,region}` |
| `undo` | — | — | `{undone}` |
| `redo` | — | — | `{redone}` |

### Perception tools

`view_page` and `view_region` return SVG markup in `data` for `format=svg`. For `format=png`,
`data` is unprefixed base64-encoded PNG bytes. PNG requires the optional renderer; an unavailable
renderer maps to `render_unavailable`.

`get_strokes` applies all supplied filters conjunctively:

- `region`: bounding-box intersection;
- `stroke_ids`: membership in the supplied set;
- `author`: `user` or `agent`;
- `since_ms`: `created_at_ms >= since_ms`;
- `visible_only`: skip invisible layers when true (default true); and
- `include_points`: include full six-value `points` when true (default true).

Results remain in document layer order and stroke order. Each stroke record contains `id`,
`layer_id`, `layer_name`, `author`, `created_at_ms`, `duration_ms`, `bbox`, `style`, `point_count`,
and optional `points`. `stroke_count` is the number of records in this response.

### Action tools

`add_stroke` creates exactly one agent stroke. Defaults are `color=#1a1a1a`, `width=2`, and
`brush=pen`. Width MUST be positive; brush MUST be `pen`, `marker`, or `highlighter`.

`erase` requires exactly one selector. Supplying both selectors is `invalid_argument`.
Unknown IDs, non-intersecting strokes, and locked targets are unchanged and absent from `erased`.
Duplicate IDs are treated once. Repeating an erase of already-erased IDs is therefore a
successful no-op.

`select` replaces the current selection. It accepts at most one selector; supplying both is
`invalid_argument`, while no selector clears the selection. `selected` is sorted lexicographically for
deterministic JSON, and `bounds` is the union of resolvable selected stroke bounds or `null` for
an empty/unresolvable selection.

`move` translates explicit IDs or the current selection. Duplicate IDs are treated once. It returns the number moved and
preserves IDs, author, style, capture time, and layer. Unknown or locked IDs are skipped.

`highlight` draws one horizontal highlighter stroke through the region center. Its width is the
region height (minimum one page unit), default color is `#ffe066`, and the result remains
non-destructive agent ink.

`write_text` lays out `text` at the top-left of `region`, wraps it, and selects the largest
readable size unless a positive `size` is supplied. `style=print` is the only shipped style;
`style=user_font` is reserved and maps to `capability_unavailable`. All generated glyph strokes
form one atomic edit.

`undo` and `redo` return the edit label that was applied, or `null` when the corresponding stack
is empty. An empty stack is a successful no-op.

## Designed read pagination and limits (not shipped)

Baseline `get_strokes` has no pagination arguments or response field: it returns every matching
record and `stroke_count == length(strokes)`. The authoritative Phase 1 manifest therefore does
not advertise `limit`, `cursor`, or `next_cursor`.

A future transport MAY advertise `capabilities.read_pagination` and extend only that advertised
`get_strokes` schema with `limit` and `cursor`. `limit` is an integer from 1 through 1000; the
transport default is 100. `cursor` is an opaque UTF-8 string no longer than 4096 bytes. Such a
host MUST return at most `limit` records and add `next_cursor`, using `null` when the query is
complete.

A cursor MUST bind to the document, page, current state revision, ordering, authorization scope,
and complete filter set, including `include_points`. Clients MUST pass it back unchanged and MUST
repeat the same filters. A host MUST return `cursor_invalid` for a mismatched query and either
serve a consistent retained snapshot or return `cursor_expired` after a relevant mutation; it
MUST NOT silently continue against a different snapshot.

Clients MUST NOT send the extension fields unless `read_pagination` is advertised and MUST NOT
fabricate a cursor from baseline ordering or IDs.

Every remote host MUST advertise finite limits for request bytes, render output bytes,
`add_stroke` points, ID-filter items, and `write_text` UTF-8 bytes. The following protocol limits
always apply:

| Item | v1 limit |
|---|---:|
| advertised `get_strokes.limit` | 1000 |
| cursor length | 4096 UTF-8 bytes |
| optional batch requests | 64 |

Exceeding a limit returns `limit_exceeded`; a host MUST NOT silently truncate a mutation. A read
may be shortened only through the documented `limit`/`next_cursor` mechanism. Clients SHOULD use
ICF v0 rather than an unbounded `get_strokes(include_points=true)` result for model context.

## Optional request batching

There is no `add_strokes` tool in the v1 core. A transport MAY advertise
`capabilities.batch_requests` and accept an ordered request array. Clients MUST NOT send this
shape unless the capability is advertised.

The batch request schema is:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "additionalProperties": false,
  "required": ["requests"],
  "properties": {
    "atomic": {"type": "boolean", "default": false},
    "requests": {
      "type": "array",
      "minItems": 1,
      "maxItems": 64,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "tool", "arguments"],
        "properties": {
          "id": {"type": "string", "minLength": 1, "maxLength": 256},
          "tool": {"type": "string", "minLength": 1},
          "arguments": {"type": "object"}
        }
      }
    }
  }
}
```

Request IDs MUST be unique within the array. Items execute in array order. With `atomic=false`,
each item has independent success/failure and earlier successes remain committed. The response is
the normal success envelope with ordered item envelopes:

```json
{
  "ok": true,
  "result": {
    "items": [
      {"id": "one", "ok": true, "result": {"stroke_id": "st_...", "bbox": [0, 0, 1, 1]}},
      {"id": "two", "ok": false, "error": {
        "code": "invalid_argument",
        "message": "erase needs one selector",
        "details": {},
        "retryable": false
      }}
    ]
  }
}
```

The batch item response schema is:

```json
{
  "oneOf": [
    {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "ok", "result"],
      "properties": {
        "id": {"type": "string"},
        "ok": {"const": true},
        "result": {"type": "object"}
      }
    },
    {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "ok", "error"],
      "properties": {
        "id": {"type": "string"},
        "ok": {"const": false},
        "error": {
          "type": "object",
          "additionalProperties": false,
          "required": ["code", "message", "details", "retryable"],
          "properties": {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "details": {"type": "object"},
            "retryable": {"type": "boolean"}
          }
        }
      }
    }
  ]
}
```

With `atomic=true`, the host MUST validate every item first and then commit the complete ordered
batch as one transaction/history entry. Any failure rolls back document, selection, and history
state and returns a top-level `ok=false`, `code=batch_failed`, with `failed_id` and the underlying
item error in `details`. Reads in a successful atomic batch observe preceding items. A host unable
to provide rollback MUST advertise `atomic=false` and reject `atomic=true` with
`capability_unavailable`.

## Reserved capabilities

The following names are reserved but are not part of the shipped v1 core:

| Reserved tool | Intended role |
|---|---|
| `describe_page` | Recognized text/diagram/scene description. |
| `search_ink` | Semantic or vector search. |
| `get_events` | Low-rate committed edit cursor, specified below. |
| `anchor` | Durable semantic reference to strokes or a region. |
| `draw_shape` | Higher-level primitive/diagram action. |

Absence from `tool_manifest()` means unavailable. A binding MUST return `unknown_tool`, not a
placeholder response, when one of these names is called without being advertised.

## Designed event cursor protocol (not shipped)

This section reserves deterministic behavior for a future advertised `get_events` tool. Phase 1
hosts omit it and omit or set `capabilities.event_cursor.supported=false`.

`get_events` describes committed edits such as stroke addition, erase, move, undo, and redo. It
is not a 120–240 Hz stylus-sample channel and MUST NOT be used to transport raw capture telemetry.
UIM remains the persistence snapshot; events are a separate, bounded synchronization plane.

Proposed input:

```json
{
  "cursor": null,
  "start": "head",
  "limit": 100,
  "wait_ms": 0
}
```

- On the first call, `cursor` is `null` and `start` is REQUIRED: `head` starts after the current
  event head; `retained` starts at the oldest retained event.
- On continuation calls, `cursor` is REQUIRED and `start` MUST be absent.
- `limit` is 1 through 1000, default 100. `wait_ms` is 0 through the host-advertised long-poll
  maximum; zero returns immediately.

Proposed result:

```json
{
  "events": [
    {
      "event_id": "ev_01J...",
      "revision": 42,
      "page_id": "pg_...",
      "occurred_at_ms": 1783639700000,
      "kind": "edit.committed",
      "actor": "agent",
      "payload": {
        "tool": "move",
        "added_stroke_ids": ["st_..."],
        "removed_stroke_ids": ["st_..."]
      }
    }
  ],
  "next_cursor": "opaque-host-value",
  "has_more": false,
  "head_revision": 42
}
```

Each event requires a unique non-empty `event_id`, a positive integer `revision`, the affected
`page_id`, non-negative epoch `occurred_at_ms`, `actor` (`user`, `agent`, or `system`), and an
object `payload`. Initial event kinds are `edit.committed`, `edit.undone`, and `edit.redone`.
Payload stroke-ID arrays contain unique stable IDs; a move can name the same ID in both added and
removed arrays because it replaces immutable geometry while preserving identity.

Future implementations MUST obey these cursor rules:

1. Cursors are opaque, integrity-protected, scoped to one document and authorization context,
   and encode or reference the position immediately after the last delivered event.
2. Repeating the same request cursor yields the same retained event sequence. Advancing with
   `next_cursor` yields each committed revision once and in strictly increasing revision order.
3. One successful atomic tool call or atomic batch consumes one revision. A failed or rolled-back
   call consumes none. Undo and redo create new revisions; they do not rewrite old events.
4. `next_cursor` is returned even for an empty page so the client can continue from an exact head.
   `has_more` is true only when retained events remain immediately readable.
5. Expired history returns `cursor_expired` with a fresh `restart_cursor` and
   `snapshot_required=true` in `details`. Invalid scope or tampering returns `cursor_invalid`.
6. Event payloads contain stable IDs and edit facts, not necessarily full stroke points. A client
   resolves current geometry with `get_strokes` or a new ICF snapshot.

The snapshot-plus-cursor handoff must be atomic before this capability can ship; otherwise an edit
between snapshot capture and cursor acquisition could be lost. This is why the protocol is fully
designed here but remains unadvertised in Phase 1.
