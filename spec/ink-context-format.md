# Ink Context Format v0

Protocol identifier: `ink-context/v0`

Status: supported legacy specification. Payloads that claim this exact identifier MUST follow
this document.

Ink Context Format (ICF) is a bounded, model-facing snapshot of one page. It combines raster
perception metadata, compact vector ink, and optional recognized semantics. Image bytes travel
beside the JSON payload as a model image/input block.

ICF is not a persistence or interchange format; [Neeh UIM Profile v1](uim-profile-v1.md) fills
that role. It is also not a live sample stream, edit log, prompt format, or provider-specific
tool schema. Agent actions use the [Neeh Tool Surface v1](tool-surface-v1.md).

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are normative requirements.

## Data model

An ICF v0 payload is a UTF-8 JSON object with exactly these top-level members:

```json
{
  "schema": "ink-context/v0",
  "page": {
    "id": "pg_...",
    "width": 1000.0,
    "height": 1414.0,
    "background": "#ffffff"
  },
  "raster": {
    "format": "png",
    "transport": "attached_image",
    "coordinate_space": "page",
    "region": null
  },
  "vector": {
    "page_id": "pg_...",
    "width": 1000.0,
    "height": 1414.0,
    "region": null,
    "stroke_count": 0,
    "included_stroke_count": 0,
    "omitted_older_stroke_count": 0,
    "truncated": false,
    "points_policy": "sampled up to 12 points per stroke",
    "strokes": []
  },
  "semantics": []
}
```

All numbers MUST be finite JSON numbers. IDs MUST be non-empty strings and are opaque to
consumers. A consumer MUST compare the complete `schema` string, not just its numeric suffix.

### Coordinate and time conventions

- Page coordinates use the page's logical units. `(0, 0)` is the top-left, x increases right,
  and y increases down.
- A region or bounding box is `[min_x, min_y, max_x, max_y]`, with `min_x <= max_x` and
  `min_y <= max_y`. Zero-area boxes are valid.
- Raster metadata, vector coordinates, bounding boxes, and semantic regions MUST refer to the
  same page coordinate space.
- `created_at_ms` is Unix epoch time in integer milliseconds.
- Point `t_ms` is a non-negative integer offset from its stroke's `created_at_ms`. Point order
  is capture order; offsets MUST be non-decreasing.
- Pressure is in `[0, 1]`. Tilt uses the W3C Pointer Events convention in degrees and is in
  `[-90, 90]` on each axis.

## Page and raster records

`page.id`, `page.width`, `page.height`, and `page.background` are REQUIRED. Width and height
MUST be greater than zero. `background` MUST be a CSS hex color in `#rgb` or `#rrggbb` form.

ICF v0 supports PNG raster context only:

| Field | Requirement |
|---|---|
| `format` | MUST be `png`. |
| `transport` | MUST be `attached_image`. |
| `coordinate_space` | MUST be `page`. |
| `region` | REQUIRED: `null` for the full page or crop bounds for a regional snapshot. |

The `raster` object MUST NOT contain image bytes, base64 data, URLs, or provider-specific image
objects. The transport MUST attach exactly one PNG image beside the JSON. If `raster.region` is a
box, the attached image MUST depict that region; if it is `null`, it MUST depict the full page.

## Vector record

`vector.page_id`, `width`, and `height` MUST equal the corresponding `page` values.
`vector.region` is either `null` for a full-page query or the region used to select strokes, and
MUST equal `raster.region`. Region matching is bounding-box intersection and includes strokes
touching the boundary.

The count fields have distinct meanings:

| Field | Meaning |
|---|---|
| `stroke_count` | Total eligible strokes before the snapshot cap. |
| `included_stroke_count` | Number of records actually present in `strokes`. |
| `omitted_older_stroke_count` | Eligible records omitted by the cap. |
| `truncated` | Whether any eligible record was omitted. |

These invariants MUST hold:

```text
included_stroke_count == length(strokes)
omitted_older_stroke_count == stroke_count - included_stroke_count
truncated == (omitted_older_stroke_count > 0)
0 <= included_stroke_count <= stroke_count
```

Eligible strokes are ordered by document layer order and then by stroke order within each layer.
When a cap is applied, the producer MUST retain the newest matching tail of the eligible sequence
and MUST preserve the retained records' relative document/layer order. This makes truncation
deterministic while prioritizing recent ink. A producer MUST NOT silently drop strokes without
updating all four count fields.

`points_policy` is an informational string. It MUST be either `all points included` or the exact
form `sampled up to <N> points per stroke`, where `<N>` is a decimal integer of at least two.

### Stroke record

Every entry in `vector.strokes` has this shape:

```json
{
  "id": "st_...",
  "layer_id": "ly_...",
  "layer_name": "ink",
  "author": "user",
  "created_at_ms": 1783639700000,
  "duration_ms": 80,
  "bbox": [100.0, 100.0, 260.0, 140.0],
  "style": {
    "color": "#1a1a1a",
    "width": 2.0,
    "opacity": 1.0,
    "brush": "pen"
  },
  "point_count": 3,
  "points_sample": [
    [100.0, 100.0, 0, 1.0, 0.0, 0.0],
    [180.0, 140.0, 40, 1.0, 0.0, 0.0],
    [260.0, 100.0, 80, 1.0, 0.0, 0.0]
  ]
}
```

Requirements:

- `id`, `layer_id`, and `layer_name` are REQUIRED. Stroke IDs MUST remain stable across move and
  style edits.
- `author` MUST be `user` or `agent`.
- `duration_ms` MUST equal the final full point's `t_ms` minus the first full point's `t_ms` and
  MUST be non-negative.
- `bbox` MUST enclose every full point. It describes the full stroke, not only sampled points.
- `style.color` MUST be `#rgb` or `#rrggbb`; `width` MUST be greater than zero; `opacity` MUST be
  in `(0, 1]`; and `brush` MUST be `pen`, `marker`, or `highlighter`.
- `point_count` is the full point count and MUST be at least one.
- Each `points_sample` item is exactly `[x, y, t_ms, pressure, tilt_x, tilt_y]`.

When `points_policy` is `all points included`, `points_sample` MUST contain every full point. For
sampling cap `N`:

1. If `point_count <= N`, `points_sample` MUST contain every point.
2. Otherwise it MUST contain `N` points. For output index `i` from `0` through `N-1`, the source
   index is round-half-to-even of `i * (point_count - 1) / (N - 1)`.
3. The first and last full points MUST be present, sampled points MUST remain in source order,
   and the selection MUST be deterministic for the same stroke and `N`.

A consumer MUST use `point_count == length(points_sample)` to determine whether the geometry is
complete. It MUST NOT treat a sampled polyline as lossless geometry.

## Semantic records

`semantics` is a list of optional recognizer or scene-graph assertions. An item has the following
closed shape; kind-specific data beyond `text` requires a later ICF version.

```json
{
  "id": "rg_...",
  "kind": "handwritten_text",
  "region": [80.0, 80.0, 340.0, 180.0],
  "stroke_ids": ["st_..."],
  "text": "x^3 = ?",
  "confidence": 0.83,
  "source": "multimodal_llm"
}
```

- `id` and `kind` are REQUIRED non-empty strings. Semantic IDs MUST be unique in the payload.
- At least one of `region` or a non-empty `stroke_ids` list is REQUIRED.
- Every `stroke_ids` entry MUST resolve to an included `vector.strokes` record and MUST be
  unique within the semantic item.
- `text` and `source`, when present, MUST be non-empty strings. `source` identifies the producer,
  not a guarantee of correctness.
- `confidence`, when present, MUST be in `[0, 1]`. Absence means unknown, not zero or one.
- Semantic assertions MUST NOT mutate, replace, or duplicate the underlying ink.

An empty list is valid and is the default.

## Validation and conformance

A conforming producer MUST:

1. emit the exact `ink-context/v0` identifier and all REQUIRED fields;
2. validate coordinate, count, author, style, time, and semantic-reference invariants;
3. make raster and vector context describe the same page and requested region;
4. use deterministic truncation and point sampling; and
5. keep image bytes outside the JSON object.

A conforming consumer MUST reject a payload with an unsupported `schema`, inconsistent counts,
invalid bounds, unresolved semantic stroke references, or mismatched page/vector identity. It MAY
accept the JSON without an attached image for storage or diagnostics, but MUST treat raster
perception as unavailable.

Objects in v0 are closed: producers MUST NOT add fields not defined here. A future compatible or
breaking shape receives a new protocol identifier. Library releases and ICF versions are
independent; callers should use `neeh.protocol.protocol_versions()` to discover support.

## Security and size handling

ICF is untrusted input at a transport boundary. Consumers SHOULD impose JSON byte, stroke,
semantic-item, and point-sample limits before allocation; reject non-finite numbers even if a
parser accepts them; and decode attached images with normal image-bomb protections. Reducing a
snapshot cap is valid only when the count and truncation invariants remain accurate.
