# M1 summary

Ledger cells: 924 (latest row per key). Context token cost = model-reported
input tokens minus the
model's CTRL (empty-context) arm mean, which removes CLI scaffolding overhead.

| model | arm | family | n | score | input tok | Δctx tok | ctx chars | fail |
|---|---|---|---|---|---|---|---|---|
| default | CTRL | T2 | 6 | 0.000 | 12210 | +0 | 0 | 0% |
| default | CTRL | T5 | 18 | 0.000 | 12237 | +27 | 0 | 0% |
| default | CTRL | T6 | 12 | 0.250 | 12221 | +11 | 0 | 0% |
| default | E3 | T4 | 10 | 0.800 | 13436 | +1226 | 1785 | 0% |
| default | E3 | T5 | 18 | 0.556 | 13868 | +1658 | 2467 | 0% |
| default | E3 | T6 | 12 | 0.833 | 13610 | +1400 | 2064 | 0% |
| default | E4 | T2 | 6 | 1.000 | 13045 | +834 | 1610 | 0% |
| default | E4 | T5 | 18 | 1.000 | 15566 | +3356 | 7318 | 0% |
| default | E4 | T6 | 12 | 0.917 | 14928 | +2718 | 5891 | 0% |
| default | E5 | T1 | 12 | 0.308 | 13157 | +946 | 1477 | 0% |
| default | E5 | T2 | 6 | 1.000 | 12487 | +277 | 329 | 0% |
| default | E5 | T3 | 12 | 0.583 | 12499 | +288 | 329 | 0% |
| default | E5 | T4 | 18 | 0.667 | 13377 | +1167 | 1860 | 0% |
| default | E5 | T5 | 18 | 0.778 | 13387 | +1176 | 1860 | 0% |
| default | E5 | T6 | 12 | 0.500 | 13170 | +960 | 1477 | 0% |
| default | E6 | T1 | 12 | 1.000 | 14072 | +1862 | 0 | 0% |
| default | E6 | T2 | 6 | 1.000 | 14058 | +1848 | 0 | 0% |
| default | E6 | T3 | 12 | 1.000 | 14068 | +1857 | 0 | 0% |
| default | E6 | T4 | 18 | 0.000 | 22941 | +10730 | 0 | 0% |
| default | E6 | T5 | 18 | 0.667 | 15669 | +3459 | 0 | 0% |
| default | E6 | T6 | 12 | 0.917 | 14069 | +1859 | 0 | 0% |
| default | E7 | T2 | 6 | 0.833 | 14641 | +2431 | 722 | 0% |
| default | E7 | T5 | 18 | 0.833 | 15993 | +3782 | 2924 | 0% |
| default | E7 | T6 | 12 | 1.000 | 15645 | +3435 | 2373 | 0% |
| default | E7v | T2 | 6 | 0.333 | 12831 | +620 | 722 | 0% |
| default | E7v | T5 | 18 | 1.000 | 14182 | +1972 | 2924 | 0% |
| default | E7v | T6 | 12 | 0.917 | 13836 | +1626 | 2373 | 0% |
| default-high | CTRL | T1 | 12 | 0.000 | 15702 | +16 | 0 | 50% |
| default-high | CTRL | T3 | 12 | 0.500 | 15690 | +5 | 0 | 0% |
| default-high | CTRL | T4 | 18 | 0.000 | 15686 | +0 | 0 | 28% |
| default-high | E0 | T1 | 12 | 1.000 | 17479 | +1793 | 0 | 0% |
| default-high | E0 | T2 | 6 | 1.000 | 17018 | +1333 | 0 | 0% |
| default-high | E0 | T3 | 12 | 1.000 | 17476 | +1790 | 0 | 0% |
| default-high | E0 | T4 | 18 | 0.000 | 17470 | +1784 | 0 | 0% |
| default-high | E0 | T5 | 18 | 0.556 | 17029 | +1343 | 0 | 0% |
| default-high | E0 | T6 | 12 | 0.500 | 17030 | +1345 | 0 | 0% |
| default-high | E1a | T1 | 12 | 1.000 | 26415 | +10729 | 17344 | 0% |
| default-high | E1a | T2 | 6 | 1.000 | 18273 | +2588 | 2553 | 0% |
| default-high | E1a | T3 | 12 | 1.000 | 18730 | +3045 | 2553 | 0% |
| default-high | E1a | T4 | 18 | 1.000 | 29035 | +13349 | 22274 | 0% |
| default-high | E1a | T5 | 18 | 1.000 | 28601 | +12916 | 22274 | 0% |
| default-high | E1a | T6 | 12 | 1.000 | 25959 | +10273 | 17344 | 0% |
| default-high | E1b | T1 | 12 | 0.917 | 24724 | +9038 | 17344 | 0% |
| default-high | E1b | T2 | 6 | 0.500 | 16510 | +824 | 2553 | 0% |
| default-high | E1b | T3 | 12 | 1.000 | 17003 | +1317 | 2553 | 0% |
| default-high | E1b | T4 | 18 | 1.000 | 27321 | +11635 | 22274 | 0% |
| default-high | E1b | T5 | 18 | 1.000 | 26884 | +11199 | 22274 | 0% |
| default-high | E1b | T6 | 12 | 1.000 | 24294 | +8609 | 17344 | 0% |
| default-high | E2 | T1 | 12 | 0.830 | 17228 | +1543 | 2043 | 0% |
| default-high | E2 | T2 | 6 | 0.833 | 15922 | +236 | 632 | 0% |
| default-high | E2 | T3 | 12 | 1.000 | 16378 | +692 | 632 | 0% |
| default-high | E2 | T4 | 18 | 0.722 | 17502 | +1816 | 2513 | 0% |
| default-high | E2 | T5 | 18 | 0.667 | 17078 | +1393 | 2513 | 0% |
| default-high | E2 | T6 | 12 | 0.667 | 18348 | +2663 | 2043 | 0% |
| default-high | E3 | T1 | 12 | 0.601 | 22556 | +6870 | 2064 | 0% |
| default-high | E3 | T2 | 6 | 1.000 | 15906 | +220 | 856 | 0% |
| default-high | E3 | T3 | 12 | 1.000 | 15918 | +232 | 856 | 0% |
| default-high | E3 | T4 | 8 | 0.667 | 17362 | +1677 | 3320 | 62% |
| default-high | E4 | T1 | 12 | 0.754 | 18412 | +2727 | 5891 | 0% |
| default-high | E4 | T3 | 12 | 1.000 | 16539 | +854 | 1610 | 0% |
| default-high | E4 | T4 | 18 | 1.000 | 19006 | +3320 | 7318 | 0% |
| default-high | E7 | T1 | 12 | 1.000 | 18649 | +2964 | 2373 | 0% |
| default-high | E7 | T3 | 12 | 1.000 | 17627 | +1942 | 722 | 0% |
| default-high | E7 | T4 | 18 | 1.000 | 18954 | +3269 | 2924 | 0% |
| default-high | E7v | T1 | 12 | 0.910 | 16876 | +1191 | 2373 | 0% |
| default-high | E7v | T3 | 12 | 1.000 | 15880 | +194 | 722 | 0% |
| default-high | E7v | T4 | 18 | 1.000 | 17165 | +1479 | 2924 | 0% |
| default-low | E0 | T1 | 12 | 1.000 | 17034 | — | 0 | 0% |
| default-low | E0 | T2 | 6 | 1.000 | 16970 | — | 0 | 0% |
| default-low | E0 | T3 | 12 | 1.000 | 17030 | — | 0 | 0% |
| default-low | E0 | T4 | 18 | 0.000 | 17024 | — | 0 | 0% |
| default-low | E0 | T5 | 17 | 0.588 | 17024 | — | 0 | 0% |
| default-low | E0 | T6 | 1 | 1.000 | 16953 | — | 0 | 0% |

## Pareto view (score vs Δ context tokens, per model × family)

**default — T1**
- E5: score 0.308 at +946 tok  ← frontier
- E6: score 1.000 at +1862 tok  ← frontier

**default — T2**
- E5: score 1.000 at +277 tok  ← frontier
- E7v: score 0.333 at +620 tok
- E4: score 1.000 at +834 tok
- E6: score 1.000 at +1848 tok
- E7: score 0.833 at +2431 tok

**default — T3**
- E5: score 0.583 at +288 tok  ← frontier
- E6: score 1.000 at +1857 tok  ← frontier

**default — T4**
- E5: score 0.667 at +1167 tok  ← frontier
- E3: score 0.800 at +1226 tok  ← frontier
- E6: score 0.000 at +10730 tok

**default — T5**
- E5: score 0.778 at +1176 tok  ← frontier
- E3: score 0.556 at +1658 tok
- E7v: score 1.000 at +1972 tok  ← frontier
- E4: score 1.000 at +3356 tok
- E6: score 0.667 at +3459 tok
- E7: score 0.833 at +3782 tok

**default — T6**
- E5: score 0.500 at +960 tok  ← frontier
- E3: score 0.833 at +1400 tok  ← frontier
- E7v: score 0.917 at +1626 tok  ← frontier
- E6: score 0.917 at +1859 tok
- E4: score 0.917 at +2718 tok
- E7: score 1.000 at +3435 tok  ← frontier

**default-high — T1**
- E7v: score 0.910 at +1191 tok  ← frontier
- E2: score 0.830 at +1543 tok
- E0: score 1.000 at +1793 tok  ← frontier
- E4: score 0.754 at +2727 tok
- E7: score 1.000 at +2964 tok
- E3: score 0.601 at +6870 tok
- E1b: score 0.917 at +9038 tok
- E1a: score 1.000 at +10729 tok

**default-high — T2**
- E3: score 1.000 at +220 tok  ← frontier
- E2: score 0.833 at +236 tok
- E1b: score 0.500 at +824 tok
- E0: score 1.000 at +1333 tok
- E1a: score 1.000 at +2588 tok

**default-high — T3**
- E7v: score 1.000 at +194 tok  ← frontier
- E3: score 1.000 at +232 tok
- E2: score 1.000 at +692 tok
- E4: score 1.000 at +854 tok
- E1b: score 1.000 at +1317 tok
- E0: score 1.000 at +1790 tok
- E7: score 1.000 at +1942 tok
- E1a: score 1.000 at +3045 tok

**default-high — T4**
- E7v: score 1.000 at +1479 tok  ← frontier
- E3: score 0.667 at +1677 tok
- E0: score 0.000 at +1784 tok
- E2: score 0.722 at +1816 tok
- E7: score 1.000 at +3269 tok
- E4: score 1.000 at +3320 tok
- E1b: score 1.000 at +11635 tok
- E1a: score 1.000 at +13349 tok

**default-high — T5**
- E0: score 0.556 at +1343 tok  ← frontier
- E2: score 0.667 at +1393 tok  ← frontier
- E1b: score 1.000 at +11199 tok  ← frontier
- E1a: score 1.000 at +12916 tok

**default-high — T6**
- E0: score 0.500 at +1345 tok  ← frontier
- E2: score 0.667 at +2663 tok  ← frontier
- E1b: score 1.000 at +8609 tok  ← frontier
- E1a: score 1.000 at +10273 tok

**default-low — T1**
- E0: score 1.000 at tok n/a  ← frontier

**default-low — T2**
- E0: score 1.000 at tok n/a  ← frontier

**default-low — T3**
- E0: score 1.000 at tok n/a  ← frontier

**default-low — T4**
- E0: score 0.000 at tok n/a  ← frontier

**default-low — T5**
- E0: score 0.588 at tok n/a  ← frontier

**default-low — T6**
- E0: score 1.000 at tok n/a  ← frontier

