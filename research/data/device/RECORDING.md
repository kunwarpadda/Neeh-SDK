# Real-ink recording kit

Record these six short sessions on a stylus-capable tablet using a compatible
handwriting application. The full set takes about 15–20 minutes. Sessions 2 and 5
are especially valuable because they contain real correction and
erase/rewrite history that final-page ink corpora do not preserve.

**Status 2026-07-15**: `s1_notes`, `s2_math`, `s3_diagram`, `s4_dense` are
recorded (`research/data/device/raw/`); `s5_edit` and `s6_crossouts` are not
(time-boxed). Concretely missing until they land: real undo/redo events and
genuine scribble cross-outs -- both are still exercised only by the synthetic
fixture (`spec/fixtures/neeh-device-capture-v1.session.json`), not by
real device data. Every capture so far is also single-page.

Open **The Lab → Research capture** and enable the mode, which is **off by
default**, before the first stroke of each session. Capture is per notebook.
Raw stylus samples and edit history must be recorded from the start; enabling
capture only at export time cannot reconstruct earlier events.

> A normal `.tink` v4 export is not sufficient for this study. It contains
> final ribbon geometry and document metadata, but not raw point timestamps or
> erased/replaced stroke history. Always export the research bundle.

## Research bundle

Each original export is a `.neeh-capture.zip` ZIP containing exactly:

```text
session.tink
session.events.json
```

- `session.tink` is the notebook/document export.
- `session.events.json` is a `neeh-device-capture/v1` capture. It preserves raw
  timestamped samples and semantic history such as stroke creation, erasure,
  undo/redo, and page changes so the SDK can recover visible, crossed-out,
  erased, replaced, and restored ink.

Keep both members together in the original ZIP. Do not substitute a standalone
`.tink`, PDF, PNG, SVG, UIM, or an extracted/repacked archive.

## Record and export one session

1. Start with a fresh notebook named for the session, such as `s1_notes`.
2. Open **The Lab → Research capture** and turn it on for that notebook before
   writing. Leave it enabled until export.
3. Perform the matching script below using the stylus. Use the app's real
   eraser, scratch-erase, undo, or redo controls where the script asks for
   those operations; do not imitate erasure with white ink.
4. Open the notebook menu and choose **Export → Research bundle**. Android's
   create-document picker proposes `<notebook>.neeh-capture.zip`; save it with
   the matching session name when practical.
5. Transfer the untouched ZIP to the matching raw session directory on the
   workstation and add `NOTES.txt` beside it.
6. Confirm that the archive contains the two expected members:

   ```sh
   unzip -Z1 research/data/device/raw/s1_notes/s1_notes.neeh-capture.zip
   # session.tink
   # session.events.json
   ```

Exporting while capture is active finalizes the session and turns capture off.
**Research bundle** remains listed while capture is off so a completed sidecar
can be exported again. If the notebook has no captured sidecar, the app asks
you to enable research capture and write first.

## Continuing a session across multiple sittings

The device recorder has no way to resume a prior session in place: every
capture start re-derives whatever ink is already on the page and records it
fresh, so re-enabling capture on a notebook that already has a finalized
sidecar starts an independent new bundle (the recorder's "Replace & start" dialog
before this is expected and safe -- nothing on the notebook itself is lost).

If a sitting gets interrupted, or you want to keep writing after an export,
just export, re-enable capture on the same notebook, and keep going -- as many
times as needed. Feed the resulting ordered list of bundles to
`neeh.adapters.device_capture.stitch_device_captures()`, which verifies each
bundle's re-seeded ink against the prior bundle's actual final state and
splices them into one continuous session, indistinguishable from an
uninterrupted recording:

```python
import json, zipfile
from neeh.adapters.device_capture import stitch_device_captures, import_device_capture

payloads = []
for path in ["s2_math_part1.neeh-capture.zip", "s2_math_part2.neeh-capture.zip"]:
    with zipfile.ZipFile(path) as z:
        payloads.append(json.loads(z.read("session.events.json")))

stitched = stitch_device_captures(payloads)  # chronological order
imported = import_device_capture(stitched)
```

Keep every part's original `.neeh-capture.zip` under the session's raw
directory (e.g. `s2_math.part1.neeh-capture.zip`, `s2_math.part2....`) rather
than only the stitched result -- the stitch is a derived, reproducible view.

## Raw data layout

Store one original bundle and one notes file per session:

```text
research/data/device/raw/
  s1_notes/
    s1_notes.neeh-capture.zip
    NOTES.txt
  s2_math/
    s2_math.neeh-capture.zip
    NOTES.txt
  s3_diagram/
    s3_diagram.neeh-capture.zip
    NOTES.txt
  s4_dense/
    s4_dense.neeh-capture.zip
    NOTES.txt
  s5_edit/
    s5_edit.neeh-capture.zip
    NOTES.txt
  s6_crossouts/
    s6_crossouts.neeh-capture.zip
    NOTES.txt
```

The filename may retain the app's notebook-derived name if Android has already
created it; the containing session directory is authoritative.

## `NOTES.txt`

Use this template for every session:

```text
Device model:
Android version:
App build (version/code or commit):
Session name:
Pressure available (yes/no/unknown):
Tilt available (yes/no/unknown):
Anything unusual:
```

Mention interrupted input, accidental gestures, app restarts, page changes,
unexpected palm input, or unavailable sensors under `Anything unusual`.

## Session scripts

1. **s1_notes** — write a page of natural handwritten notes, 5–10 lines, on
   any topic.
2. **s2_math** — work a short derivation or calculation by hand. Make at least
   two real corrections as you go: cross out a term and rewrite it, then
   overwrite a wrong digit in place.
3. **s3_diagram** — draw a small flowchart with 4–6 boxes or shapes and labeled
   arrows connecting them.
4. **s4_dense** — make a deliberately cramped page: small writing, a margin
   annotation, and an arrow pointing from the margin into the text.
5. **s5_edit** — write a five-item list and pause for a few seconds. Erase one
   item completely with the eraser, rewrite it, add a new item at the bottom,
   cross out a different item, then exercise undo and redo once. Use a second
   page for one addition if practical so page history is represented.
6. **s6_crossouts** — write about eight short words and cross out three in
   different styles: one single strike, one double strike, and one scribble.

## Preserve raw captures

Treat `research/data/device/raw/` as immutable source evidence:

- Do not edit `session.events.json`, normalize coordinates or timestamps,
  remove device metadata, rename archive members, or overwrite/repack the ZIP.
- Do not run converters with an output path inside a raw session directory.
- Write normalized imports and generated fixtures somewhere separate, such as
  `research/data/device/derived/<session>/` or a temporary test-fixture
  directory.
- Keep personal raw recordings out of committed fixtures unless their review
  and inclusion are explicitly approved. Commit only purpose-built,
  non-personal fixtures by default.

If a raw capture must be replaced, retain the original outside the repository
and record why the replacement was made in the new `NOTES.txt`.
