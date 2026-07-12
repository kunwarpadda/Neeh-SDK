# Ink Context Format v1

Protocol identifier: `ink-context/v1`

Ink Context Format (ICF) is a bounded, model-facing snapshot of one page. Version 1 encodes
stroke geometry as compact SVG paths on an integer grid while preserving stable stroke IDs and
page-space coordinates for actions.

ICF is not a persistence format. Use the [UIM Profile v1](uim-profile-v1.md) for interchange.
ICF is also separate from the [Tool Surface v1](tool-surface-v1.md), which defines reads and
mutations.

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are normative requirements.

## Envelope

A v1 payload is a UTF-8 JSON object with exactly these top-level members:

| Member | Requirement |
|---|---|
| `schema` | MUST be `"ink-context/v1"`. |
| `page` | MUST contain `id`, `width`, `height`, and `background`. |
| `raster` | MUST describe the optional raster transported beside the JSON. |
| `ink` | MUST contain the geometry block described below. |
| `semantics` | MUST be an array; it MAY be empty. |

All numeric values MUST be finite JSON numbers. IDs MUST be non-empty strings.

## Coordinate systems

Page coordinates use logical page units with `(0, 0)` at the top left, x increasing right, and y
increasing down. Regions and bounding boxes use
`[min_x, min_y, max_x, max_y]` in page units.

The SVG path data uses the integer grid declared by `ink.grid`. Grid coordinates MUST NOT appear
in fields that a consumer may pass to a tool call. In particular, `ink.region`, `ink.bboxes`,
semantic regions, and raster regions MUST use page units.

## Page record

`page.id` is the stable page ID. `page.width` and `page.height` MUST be positive. `page.background`
MUST be a CSS hex color in `#rgb` or `#rrggbb` form.

## Raster record

The raster record has this shape:

```json
{
  "format": "png",
  "transport": "none",
  "coordinate_space": "page",
  "region": null
}
```

- `format` MUST be `png`.
- `transport` MUST be `none` or `attached_image`.
- `coordinate_space` MUST be `page`.
- `region` MUST be `null` for the full page or a page-space box for a crop.

When `transport` is `attached_image`, the transport MUST provide exactly one PNG beside the JSON.
The image MUST depict `raster.region`, or the full page when the region is `null`. Image bytes,
URLs, and provider-specific image objects MUST NOT be embedded in the ICF JSON.

## Ink record

| Field | Requirement |
|---|---|
| `encoding` | MUST be `"svg-paths/grid"`. |
| `grid` | MUST be `[width, height]` with positive integer dimensions. |
| `drawn_order` | MUST be `true`. |
| `region` | MUST be `null` or a page-space box. |
| `stroke_count` | Number of eligible strokes before the stroke limit. |
| `included_stroke_count` | Number of paths included in this payload. |
| `omitted_older_stroke_count` | Number excluded by the stroke limit. |
| `truncated` | MUST equal `omitted_older_stroke_count > 0`. |
| `svg` | Compact SVG containing the included stroke paths. |
| `bboxes` | OPTIONAL map from included stroke ID to page-space bounding box. |
| `hints` | OPTIONAL map from included stroke ID to a short `"shape, position"` label (e.g. `"loop, lower-left"`). Advisory only; consumers MUST NOT treat it as ground truth. |
| `rate_point` | OPTIONAL rate-control settings selected by the producer. |

When a producer applies a stroke limit, it MUST retain the newest eligible strokes and preserve
their relative document order.

### SVG encoding

`ink.svg` MUST contain an `<svg>` element whose `viewBox` is `0 0 grid_width grid_height`.
Each included stroke MUST appear exactly once as a self-closing `<path>`:

```xml
<path id="st_..." d="M18 18l4 1 3 -2"/>
```

The `id` attribute MUST be the stable stroke ID. The path MUST begin with an absolute integer
`M x y` command followed by zero or more relative integer `l dx dy` pairs. Paths MUST appear in
document drawing order. Duplicate IDs are invalid.

Producers MAY resample or simplify a stroke before quantization. Such processing MUST NOT change
the stroke ID or path order.

## Semantic items

Semantic items use the same shape as ICF v0. Every item MUST contain a stable `id` and `kind`,
and MUST be anchored by a page-space `region`, one or more included `stroke_ids`, or both.
Optional fields are `text`, `confidence`, `source`, and `edges`.

`confidence`, when present, MUST be between 0 and 1. `edges`, when present, MUST map non-empty
relation names to non-empty semantic item IDs. A semantic item MUST NOT reference a stroke omitted
from the payload.

## Rate control

A producer MAY choose grid size and path simplification to satisfy a character budget. When it
does, it MUST include:

```json
{
  "rate_point": {
    "grid_long_edge": 256,
    "simplify_eps_grid": 1.0
  }
}
```

`grid_long_edge` MUST be a positive integer and `simplify_eps_grid` MUST be a positive number or
`null`. If no available operating point fits the requested budget, a producer MAY return its
smallest supported representation; callers MUST compare the serialized size with their hard
transport limit.

## Regional retrieval

A host MAY send a lightweight page index and expose `fetch_ink_region` from Tool Surface v1.
The tool accepts a page-space region and returns compact SVG, the grid dimensions, page-space
bounding boxes, and stroke count for intersecting visible strokes.

Clients MUST use the returned grid to interpret SVG geometry and MUST use page-space boxes for
subsequent tool calls.

## Compatibility

Consumers MUST compare the complete `schema` identifier. Additive optional fields are permitted.
Changing a required field, coordinate rule, path grammar, or field meaning requires a new protocol
identifier.
