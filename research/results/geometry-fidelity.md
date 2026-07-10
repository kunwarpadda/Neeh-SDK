# Geometry fidelity of svg-paths/grid (offline, exact)

S0 corpus, 12 pages. Every original ink point's distance to the
decoded (encode -> parse_ink_paths -> page units) polyline, in page units
(page is 1000 x 1414). This is the physical half of icf-v1-draft open
question #3; the live E7v128/E7v512 sweep supplies the task-score half.

| grid | page kind | mean err | p95 err | max err | mean chars |
|---|---|---|---|---|---|
| 128 | text | 6.08 | 13.71 | 17.87 | 3,526 |
| 128 | shapes | 5.71 | 14.46 | 20.93 | 491 |
| 256 | text | 2.44 | 5.28 | 7.91 | 4,025 |
| 256 | shapes | 2.79 | 8.15 | 9.48 | 722 |
| 512 | text | 1.00 | 2.12 | 5.56 | 4,836 |
| 512 | shapes | 1.43 | 4.31 | 5.88 | 1,174 |

Reading: error scales inversely with grid resolution while characters grow
sub-linearly (offsets stay small). For scale, a pen stroke is ~2-3 page
units wide; errors below that are invisible at readback.
