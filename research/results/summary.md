# M1 summary

Ledger cells: 1302 (latest row per key). Context token cost = model-reported
input tokens minus the
model's CTRL (empty-context) arm mean, which removes CLI scaffolding overhead.

| model | arm | family | n | score | input tok | Δctx tok | ctx chars | fail |
|---|---|---|---|---|---|---|---|---|
| default | CTRL | T1 | 12 | 0.027 | 12243 | +33 | 0 | 0% |
| default | CTRL | T2 | 12 | 0.000 | 12210 | +0 | 0 | 0% |
| default | CTRL | T3 | 12 | 0.417 | 12222 | +12 | 0 | 0% |
| default | CTRL | T4 | 6 | 0.000 | 12214 | +4 | 0 | 0% |
| default | CTRL | T5 | 24 | 0.000 | 12236 | +26 | 0 | 0% |
| default | CTRL | T6 | 18 | 0.444 | 12222 | +12 | 0 | 0% |
| default | E0 | T1 | 12 | 0.758 | 14087 | +1877 | 0 | 0% |
| default | E0 | T2 | 6 | 0.833 | 14018 | +1808 | 0 | 0% |
| default | E0 | T3 | 12 | 1.000 | 14029 | +1819 | 0 | 0% |
| default | E0 | T4 | 6 | 0.000 | 14022 | +1812 | 0 | 0% |
| default | E0 | T5 | 6 | 0.833 | 14042 | +1832 | 0 | 0% |
| default | E0 | T6 | 6 | 0.333 | 14032 | +1822 | 0 | 0% |
| default | E1a | T1 | 12 | 0.832 | 20648 | +8438 | 12210 | 0% |
| default | E1a | T2 | 6 | 0.833 | 17917 | +5707 | 7553 | 0% |
| default | E1a | T3 | 12 | 1.000 | 17927 | +5717 | 7553 | 0% |
| default | E1a | T4 | 6 | 1.000 | 17919 | +5709 | 7553 | 0% |
| default | E1a | T5 | 6 | 0.833 | 17942 | +5732 | 7553 | 0% |
| default | E1a | T6 | 6 | 1.000 | 17929 | +5719 | 7553 | 0% |
| default | E1b | T1 | 6 | 0.354 | 21724 | +9514 | 16867 | 0% |
| default | E2 | T1 | 6 | 0.333 | 13406 | +1196 | 1386 | 0% |
| default | E2 | T2 | 6 | 0.833 | 13393 | +1183 | 1386 | 0% |
| default | E2 | T3 | 12 | 0.500 | 13405 | +1195 | 1386 | 0% |
| default | E2 | T4 | 6 | 0.667 | 13397 | +1187 | 1386 | 0% |
| default | E2 | T5 | 6 | 0.667 | 13452 | +1242 | 1386 | 0% |
| default | E2 | T6 | 6 | 0.667 | 13406 | +1196 | 1386 | 0% |
| default | E3 | T4 | 10 | 0.800 | 13436 | +1226 | 1785 | 0% |
| default | E3 | T5 | 18 | 0.556 | 13868 | +1658 | 2467 | 0% |
| default | E3 | T6 | 12 | 0.833 | 13610 | +1400 | 2064 | 0% |
| default | E4 | T2 | 6 | 1.000 | 13045 | +835 | 1610 | 0% |
| default | E4 | T5 | 18 | 1.000 | 15566 | +3356 | 7318 | 0% |
| default | E4 | T6 | 12 | 0.917 | 14928 | +2718 | 5891 | 0% |
| default | E5 | T1 | 18 | 0.205 | 12981 | +771 | 1201 | 0% |
| default | E5 | T2 | 12 | 0.917 | 12574 | +364 | 489 | 0% |
| default | E5 | T3 | 24 | 0.625 | 12585 | +375 | 489 | 0% |
| default | E5 | T4 | 24 | 0.667 | 13198 | +988 | 1557 | 0% |
| default | E5 | T5 | 24 | 0.750 | 13212 | +1002 | 1557 | 0% |
| default | E5 | T6 | 18 | 0.500 | 13005 | +795 | 1201 | 0% |
| default | E6 | T1 | 12 | 1.000 | 14072 | +1862 | 0 | 0% |
| default | E6 | T2 | 6 | 1.000 | 14058 | +1848 | 0 | 0% |
| default | E6 | T3 | 12 | 1.000 | 14068 | +1858 | 0 | 0% |
| default | E6 | T4 | 18 | 0.000 | 22941 | +10731 | 0 | 0% |
| default | E6 | T5 | 18 | 0.667 | 15669 | +3459 | 0 | 0% |
| default | E6 | T6 | 12 | 0.917 | 14069 | +1859 | 0 | 0% |
| default | E7 | T1 | 12 | 0.758 | 15200 | +2990 | 1639 | 0% |
| default | E7 | T2 | 12 | 0.833 | 14920 | +2710 | 1136 | 0% |
| default | E7 | T3 | 12 | 1.000 | 15209 | +2999 | 1551 | 0% |
| default | E7 | T4 | 6 | 1.000 | 15201 | +2991 | 1551 | 0% |
| default | E7 | T5 | 24 | 0.750 | 15800 | +3590 | 2580 | 0% |
| default | E7 | T6 | 18 | 0.944 | 15500 | +3290 | 2099 | 0% |
| default | E7b | T1 | 12 | 0.836 | 15518 | +3308 | 2200 | 0% |
| default | E7b | T3 | 12 | 1.000 | 15419 | +3209 | 1941 | 0% |
| default | E7b | T4 | 6 | 1.000 | 15410 | +3200 | 1941 | 0% |
| default | E7b | T5 | 6 | 0.167 | 15434 | +3224 | 1941 | 0% |
| default | E7b | T6 | 6 | 1.000 | 15455 | +3245 | 1941 | 0% |
| default | E7v | T1 | 12 | 0.461 | 13407 | +1197 | 1639 | 0% |
| default | E7v | T2 | 12 | 0.583 | 13109 | +899 | 1136 | 0% |
| default | E7v | T3 | 12 | 0.917 | 13399 | +1189 | 1551 | 0% |
| default | E7v | T4 | 6 | 0.778 | 13391 | +1181 | 1551 | 0% |
| default | E7v | T5 | 24 | 0.917 | 13990 | +1780 | 2580 | 0% |
| default | E7v | T6 | 18 | 0.944 | 13691 | +1481 | 2099 | 0% |
| default | E7v512 | T1 | 6 | 0.402 | 13787 | +1577 | 2201 | 0% |
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
- E5: score 0.205 at +771 tok  ← frontier
- E2: score 0.333 at +1196 tok  ← frontier
- E7v: score 0.461 at +1197 tok  ← frontier
- E7v512: score 0.402 at +1577 tok
- E6: score 1.000 at +1862 tok  ← frontier
- E0: score 0.758 at +1877 tok
- E7: score 0.758 at +2990 tok
- E7b: score 0.836 at +3308 tok
- E1a: score 0.832 at +8438 tok
- E1b: score 0.354 at +9514 tok

**default — T2**
- E5: score 0.917 at +364 tok  ← frontier
- E4: score 1.000 at +835 tok  ← frontier
- E7v: score 0.583 at +899 tok
- E2: score 0.833 at +1183 tok
- E0: score 0.833 at +1808 tok
- E6: score 1.000 at +1848 tok
- E7: score 0.833 at +2710 tok
- E1a: score 0.833 at +5707 tok

**default — T3**
- E5: score 0.625 at +375 tok  ← frontier
- E7v: score 0.917 at +1189 tok  ← frontier
- E2: score 0.500 at +1195 tok
- E0: score 1.000 at +1819 tok  ← frontier
- E6: score 1.000 at +1858 tok
- E7: score 1.000 at +2999 tok
- E7b: score 1.000 at +3209 tok
- E1a: score 1.000 at +5717 tok

**default — T4**
- E5: score 0.667 at +988 tok  ← frontier
- E7v: score 0.778 at +1181 tok  ← frontier
- E2: score 0.667 at +1187 tok
- E3: score 0.800 at +1226 tok  ← frontier
- E0: score 0.000 at +1812 tok
- E7: score 1.000 at +2991 tok  ← frontier
- E7b: score 1.000 at +3200 tok
- E1a: score 1.000 at +5709 tok
- E6: score 0.000 at +10731 tok

**default — T5**
- E5: score 0.750 at +1002 tok  ← frontier
- E2: score 0.667 at +1242 tok
- E3: score 0.556 at +1658 tok
- E7v: score 0.917 at +1780 tok  ← frontier
- E0: score 0.833 at +1832 tok
- E7b: score 0.167 at +3224 tok
- E4: score 1.000 at +3356 tok  ← frontier
- E6: score 0.667 at +3459 tok
- E7: score 0.750 at +3590 tok
- E1a: score 0.833 at +5732 tok

**default — T6**
- E5: score 0.500 at +795 tok  ← frontier
- E2: score 0.667 at +1196 tok  ← frontier
- E3: score 0.833 at +1400 tok  ← frontier
- E7v: score 0.944 at +1481 tok  ← frontier
- E0: score 0.333 at +1822 tok
- E6: score 0.917 at +1859 tok
- E4: score 0.917 at +2718 tok
- E7b: score 1.000 at +3245 tok  ← frontier
- E7: score 0.944 at +3290 tok
- E1a: score 1.000 at +5719 tok

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

