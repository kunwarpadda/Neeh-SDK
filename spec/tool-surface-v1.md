# Neeh Tool Surface v1

Protocol identifier: `neeh-tools/v1`

This specification defines the shipped tool contract between a Neeh canvas host and an
automation or model runtime. The Python reference implementation exposes fourteen tools.

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are normative requirements.

## Discovery

Python callers discover the protocol and exact input schemas at runtime:

```python
from neeh.protocol import protocol_versions
from neeh.tools import tool_manifest

assert protocol_versions()["tool_surface"] == "neeh-tools/v1"
manifest = tool_manifest()
```

The manifest has this shape:

```json
{
  "protocol": "neeh-tools/v1",
  "tools": [
    {
      "name": "view_page",
      "description": "...",
      "input_schema": {"type": "object", "properties": {}}
    }
  ]
}
```

The manifest is authoritative. A host MUST NOT accept a tool that it does not advertise. Tool
surface versions and package versions are independent; callers should use
`neeh.protocol.protocol_versions()` rather than infer support from the package version.

## Transport envelope

An out-of-process binding SHOULD accept one JSON object per request:

```json
{
  "request_id": "req_01J...",
  "tool": "get_strokes",
  "arguments": {"author": "user"}
}
```

`request_id` is optional. When supplied, it MUST be copied to the response. `arguments` MUST be
an object and MUST validate against the advertised input schema.

A successful response has this shape:

```json
{"ok": true, "result": {}, "request_id": "req_01J..."}
```

A failed response has this shape:

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

Exactly one of `result` or `error` MUST be present. `details` MUST be an object and MUST NOT expose
stack traces, credentials, provider output, or host filesystem paths.

The in-process Python API is intentionally thinner: `call_tool(canvas, name, arguments)` returns
the result directly and raises Python exceptions. A binding is responsible for mapping those
exceptions to safe wire errors.

### Error codes

| Code | Meaning | Retryable by default |
|---|---|---:|
| `invalid_request` | Malformed envelope or non-object arguments. | false |
| `unknown_tool` | Tool is absent from the advertised manifest. | false |
| `invalid_argument` | Schema, coordinate, enum, or cross-field validation failed. | false |
| `limit_exceeded` | Request or result exceeds a host limit. | false |
| `layer_locked` | The requested mutation targets locked ink. | false |
| `capability_unavailable` | An optional renderer or implementation is unavailable. | false |
| `conflict` | State changed before the operation could be applied consistently. | true |
| `internal_error` | Unexpected host failure. | true |

## Common values and invariants

- Page coordinates start at the top left, with x increasing right and y increasing down.
- A region is `[min_x, min_y, max_x, max_y]` with finite values and non-inverted bounds.
- A point is `[x, y]` or `[x, y, t_ms, pressure, tilt_x, tilt_y]`.
- Stroke, page, layer, and request IDs are opaque non-empty strings.
- Moving or restyling a stroke MUST preserve its stroke ID.
- Agent-created ink MUST use `author=agent` and the current page's agent layer.
- Locked layers MUST NOT be mutated.
- Every successful mutating tool call MUST be atomic and create at most one undo entry.
- A failed mutation MUST leave the document, selection, and history unchanged.
- A successful new edit clears redo history.
- Results MUST be JSON serializable.

Hosts SHOULD enforce and document finite limits for request bytes, result bytes, point counts,
ID-filter items, render size, and text length. A host MUST reject an oversized mutation rather
than truncate it silently.

## Core tools

| Tool | Required arguments | Optional arguments | Result |
|---|---|---|---|
| `view_page` | — | `format` | `{page_id,width,height,format,data}` |
| `view_region` | `region` | `format` | `{page_id,region,format,data}` |
| `fetch_ink_region` | `region` | — | `{page_id,region,grid,svg,bboxes,stroke_count}` |
| `get_strokes` | — | `region`, `stroke_ids`, `author`, `since_ms`, `visible_only`, `include_points` | `{page_id,width,height,region,stroke_count,strokes}` |
| `add_stroke` | `points` | `color`, `width`, `brush` | `{stroke_id,bbox}` |
| `erase` | one of `stroke_ids`, `region` | — | `{erased}` |
| `select` | — | `stroke_ids` or `region` | `{selected,bounds}` |
| `move` | `dx`, `dy` | `stroke_ids` | `{moved}` |
| `highlight` | `region` | `color` | `{stroke_id,region}` |
| `write_text` | `text`, `region` | `style`, `color`, `size` | `{stroke_ids,size,region,style}` |
| `mark` | `stroke_ids`, `kind` | `color` | `{stroke_id,kind,anchor_bbox}` |
| `insert_text` | `text`, `stroke_ids`, `position` | `color`, `size` | `{stroke_ids,size,region,anchor_bbox,original_anchor_bbox,reflow,style}` |
| `undo` | — | — | `{undone}` |
| `redo` | — | — | `{redone}` |

### Perception tools

`view_page` and `view_region` support `format=svg` and `format=png`; SVG is the default. SVG data
is returned as markup. PNG data is returned as unprefixed base64 and requires the optional PNG
renderer. `view_region` renders only the supplied page-space box.

`fetch_ink_region` returns compact ICF v1 SVG paths for visible strokes intersecting `region`.
`grid` defines the SVG coordinate space. `bboxes` and `region` remain in page units, path IDs are
stable stroke IDs, and paths follow document order.

`get_strokes` applies supplied filters conjunctively:

- `region`: bounding-box intersection;
- `stroke_ids`: membership in the supplied set;
- `author`: `user` or `agent`;
- `since_ms`: `created_at_ms >= since_ms`;
- `visible_only`: exclude invisible layers when true; and
- `include_points`: include full point arrays when true.

Results follow document layer and stroke order. Each record contains `id`, `layer_id`,
`layer_name`, `author`, `created_at_ms`, `duration_ms`, `bbox`, `style`, and `point_count`, plus
`points` when requested.

### Mutation tools

`add_stroke` creates one agent stroke. Width MUST be positive; brush MUST be `pen`, `marker`, or
`highlighter`.

`erase` requires exactly one selector. Duplicate IDs are treated once. Unknown IDs,
non-intersecting strokes, and locked targets are unchanged and absent from `erased`.

`select` replaces the current selection. Supplying no selector clears it. Supplying both selectors
is invalid. `selected` is sorted for deterministic output; `bounds` is the union of resolvable
selected stroke bounds or `null`.

`move` translates explicit IDs or the current selection. Duplicate IDs are treated once. It
preserves IDs, author, style, capture time, and layer, and returns the number moved.

`highlight` adds one non-destructive highlighter stroke through the center of `region`.

`write_text` lays out glyph strokes inside `region`, wrapping and auto-sizing unless a positive
`size` is supplied. `style=print` provides regular single-stroke lettering;
`style=handwritten` uses the cursive Hershey Script Complex face and is the default. All glyph
strokes form one undoable edit.

`mark` adds non-destructive agent ink relative to the union bounding box of `stroke_ids`. `kind`
MUST be `strike`, `circle`, `underline`, or `check`. Unknown IDs are invalid.

`insert_text` places handwritten ink `before`, `after`, `above`, or `below` the union bounding box of
`stroke_ids`. It MAY shift a bounded set of unlocked user strokes horizontally to open a gap. The
insertion and reflow MUST form one atomic edit. Locked or non-user obstacles, unsafe shifts, and
page overflow MUST fail without mutation. `reflow` reports moved IDs and translation.

`undo` and `redo` return the applied edit label, or `null` when the corresponding history stack is
empty. An empty stack is a successful no-op.

## Security

Bindings MUST authenticate and authorize callers before applying mutations. They SHOULD treat
rendered SVG and model-provided text as untrusted data, enforce timeouts and size limits, and avoid
logging full payloads when they may contain user handwriting.

## Compatibility

Consumers MUST compare the complete protocol identifier and use the advertised schemas. Adding a
required argument, removing a tool or result field, changing coordinate rules, or changing an
existing field's meaning requires a new protocol identifier.
