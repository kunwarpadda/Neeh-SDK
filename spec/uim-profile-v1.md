# Neeh UIM Profile v1

Profile identifier: `neeh-uim/v1`

Base format: Universal Ink Model (UIM) serialization 3.1.0

Status: Phase 1 persistence and interchange profile.

This specification defines the loss model and canonical mapping between a Neeh `Document` and
one UIM `InkModel`. Neeh does not define or use a bespoke `.neeh` file format. Conforming files
use UIM's RIFF/Protobuf container and SHOULD use the `.uim` extension.

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are normative requirements.

## Version identity

The external profile identifier is `neeh-uim/v1`. A canonical producer MUST write this model
property:

```text
neeh.profile = neeh-uim/v1
```

The initial prototype wrote `neeh.profile = 1`. A v1 reader MUST accept that exact legacy value
as an alias for `neeh-uim/v1`, but MUST NOT emit it. A reader MUST reject a missing property or
any other profile value rather than guessing the mapping.

Three version domains are independent:

- UIM serialization `3.1.0` defines the container and base ink model;
- Neeh profile `neeh-uim/v1` defines this mapping; and
- the `neeh` library package follows its own release version.

A change in one does not imply the same version number in another. See
[Versioning](../ARCHITECTURE.md#versioning).

## Canonical model structure

A conforming file has one primary UIM ink tree arranged in document order:

```text
document root (StrokeGroupNode)
└── page (StrokeGroupNode)
    └── layer (StrokeGroupNode)
        └── stroke (StrokeNode)
```

Requirements:

1. The root has one child per Neeh page, including empty pages.
2. A page group has one child per layer, including hidden, locked, agent, and empty layers.
3. A layer group has one `StrokeNode` per stroke.
4. Page, layer, and stroke ordering MUST match the source `Document` ordering.
5. A page child MUST be a page group, a page's child MUST be a layer group, and a layer's child
   MUST be a stroke node. v1 does not interleave arbitrary groups in the canonical tree.

Node and stroke UUIDs are deterministic UUIDv5 values in `uuid.NAMESPACE_URL`:

```text
document root: uuid5(NAMESPACE_URL, "neeh:document:" + document_id)
page group:    uuid5(NAMESPACE_URL, "neeh:page:" + page_id)
layer group:   uuid5(NAMESPACE_URL, "neeh:layer:" + layer_id)
UIM stroke:    uuid5(NAMESPACE_URL, "neeh:stroke:" + stroke_id)
```

The UUID mapping is an internal UIM identity bridge. Neeh IDs remain opaque strings and MUST be
recovered from the profile metadata, not reverse-engineered from UUIDs.

## Model properties

The following UIM model properties are REQUIRED and their values are strings:

| Property | Value |
|---|---|
| `neeh.profile` | Canonical value `neeh-uim/v1`. |
| `neeh.document.id` | Stable Neeh document ID. |
| `neeh.document.title` | Document title, including the empty string. |
| `neeh.document.created_at_ms` | Base-10 Unix epoch milliseconds. |

`neeh.document.created_at_ms` MUST parse as a signed 64-bit integer. A producer MAY add
non-`neeh.*` model properties. Unknown properties are not guaranteed to survive a
UIM → Neeh `Document` → UIM transcode.

## Knowledge-graph triples

Neeh-only structural facts are UIM semantic triples. The subject is the corresponding UIM node's
canonical `node.uri`; predicate and object are strings.

### Page group

| Predicate | Required object |
|---|---|
| `neeh:type` | `page` |
| `neeh:id` | Stable page ID |
| `neeh:width` | Finite positive decimal page width |
| `neeh:height` | Finite positive decimal page height |
| `neeh:background` | CSS hex color (`#rgb` or `#rrggbb`) |

### Layer group

| Predicate | Required object |
|---|---|
| `neeh:type` | `layer` |
| `neeh:id` | Stable layer ID |
| `neeh:name` | Layer name |
| `neeh:author` | `user` or `agent` |
| `neeh:visible` | Lowercase `true` or `false` |
| `neeh:locked` | Lowercase `true` or `false` |

### Stroke node

| Predicate | Required object |
|---|---|
| `neeh:type` | `stroke` |
| `neeh:id` | Stable stroke ID |
| `neeh:author` | `user` or `agent` |

Within a subject, each REQUIRED predicate MUST occur exactly once. Conflicting duplicate facts
make the profile invalid. Additional semantic triples MAY coexist with these facts; readers MAY
ignore them, and the reference `Document` adapter does not promise to preserve them when
transcoding. The `neeh:` predicate prefix is reserved for this profile and future Neeh profiles.

## Native UIM mapping

Information already represented by UIM stays native instead of being duplicated as triples.

### Geometry and style

- Every Neeh point contributes x/y to the UIM stroke's planar spline, in capture order.
- The UIM stroke ID is the deterministic UUID above.
- Base width, red, green, blue, and alpha use UIM path-point properties.
- Brush URIs are `neeh://brush/pen`, `neeh://brush/marker`, or
  `neeh://brush/highlighter` and reference a circular vector brush.
- Neeh `#rgb` colors expand to their equivalent `#rrggbb` value on import.

### Time, pressure, and tilt

A canonical producer creates one shared pen input configuration containing environment, input
provider, input device, sensor context, and input context. The environment includes
`app.id=neeh-sdk`.

Every stroke has one `SensorData` record linked by `sensor_data_id`:

| Neeh value | UIM representation |
|---|---|
| `Stroke.created_at_ms` | `SensorData.timestamp` in epoch milliseconds |
| `Point.t_ms` | Timestamp channel value `created_at_ms / 1000 + t_ms / 1000` seconds |
| `Point.pressure` | Normalized pressure channel, range `[0,1]`, precision 4 |
| `Point.tilt_x`, `tilt_y` | W3C tilt converted to UIM azimuth/altitude angle channels, precision 4 |

The timestamp channel uses resolution 1000 and precision 0. On import, point offsets are rounded
back to integer milliseconds relative to `SensorData.timestamp`.

UIM supports richer device and input provenance than profile v1 currently emits. The shared
configuration is a codec context, not proof that all source ink came from one physical pen.
User/agent attribution is carried by the required Neeh triples; profile v1 is not a persistent
multi-author revision log.

## Quantization and fidelity

UIM 3.1 is the interchange truth, so importing a just-exported document can normalize values.
Profile v1 guarantees exact structural fields and bounded numeric fidelity:

| Value | Required round-trip behavior |
|---|---|
| Document/page/layer/stroke order and IDs | Exact |
| Title, page geometry metadata, background, layer name/author/flags, stroke author | Exact |
| `created_at_ms` and point `t_ms` | Exact integer milliseconds |
| x/y geometry | UIM float32; reference conformance tolerance `1e-3` page units |
| Stroke width | UIM float32; reference tolerance `1e-4` page units |
| RGB color | 8 bits per channel; exact for canonical `#rrggbb` input |
| Opacity | 8-bit channel; tolerance `1/255` |
| Pressure | Precision 4 channel; tolerance `1e-4` |
| W3C tilt after azimuth/altitude conversion | Precision 4 channels; reference tolerance `0.05°` |

Tolerances apply to the reference conformance corpus's normal page range. Producers MUST reject
non-finite coordinates and out-of-range pressure/tilt before encoding.

Semantic idempotence is REQUIRED: after one normalization round trip, a second round trip MUST
produce the same Neeh `Document` values. Byte-for-byte UIM identity is not required because a
producer may allocate fresh UIM input-context and sensor-data UUIDs.

## Reader compatibility

A conforming v1 reader MUST:

1. parse the UIM 3.1 model and validate the canonical or legacy profile property;
2. require a primary ink tree and every structural property/triple listed above;
3. preserve page, layer, and stroke order;
4. reject invalid enum, boolean, numeric, tree-shape, or missing-reference data; and
5. reconstruct points, style, stable IDs, timestamps, and authorship within the stated fidelity.

A generic UIM 3.1 file is not automatically a Neeh-profile file. Missing Neeh metadata is an
error, not a cue to invent IDs or authors. Conversely, generic UIM readers can render the native
strokes without understanding Neeh triples, but removing those triples makes the result
non-conforming.

Readers MAY accept a later UIM container revision only if they can prove that it preserves every
v1 requirement; canonical v1 writers MUST emit UIM 3.1. Unknown non-Neeh properties and triples
MAY be ignored. Unknown `neeh:*` facts MUST NOT override required v1 facts.

## Conformance classes

- A **v1 producer** emits UIM 3.1, the canonical profile value, canonical tree order, all required
  properties/triples, native geometry/style/sensor data, and valid deterministic node UUIDs.
- A **v1 consumer** accepts canonical plus legacy profile identity and reconstructs the required
  document model with the validation and fidelity above.
- A **v1 round-trip adapter** satisfies both classes and semantic idempotence.

The reference adapter is `neeh.adapters.uim`. Its conformance corpus MUST cover at least:

- multiple pages and layers, including empty, hidden, locked, user, and agent layers;
- all three brushes, user and agent strokes, single-point strokes, and Unicode titles;
- exact stable IDs and millisecond timing;
- the quantization bounds above;
- rejection of generic/missing-profile and unknown-profile UIM files;
- acceptance of the legacy `neeh.profile=1` prototype; and
- semantic idempotence plus `.uim` file save/load.

## Security and resource handling

UIM input is untrusted binary data. Consumers SHOULD bound container size, tree depth, node,
stroke, point, sensor-channel, property, and triple counts before constructing a `Document`.
Consumers MUST reject dangling sensor references, impossible channel lengths, non-finite values,
and duplicate required facts. No metadata string should be executed or interpreted as a path.
