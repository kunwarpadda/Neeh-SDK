# M1 summary

Ledger rows: 252. Context token cost = model-reported input tokens minus the
model's CTRL (empty-context) arm mean, which removes CLI scaffolding overhead.

| model | arm | family | n | score | input tok | Δctx tok | ctx chars | fail |
|---|---|---|---|---|---|---|---|---|
| default | CTRL | T1 | 12 | 0.000 | 15702 | +16 | 0 | 50% |
| default | CTRL | T3 | 12 | 0.500 | 15690 | +5 | 0 | 0% |
| default | CTRL | T4 | 18 | 0.000 | 15686 | +0 | 0 | 28% |
| default | E0 | T1 | 12 | 1.000 | 17479 | +1793 | 0 | 0% |
| default | E0 | T3 | 12 | 1.000 | 17476 | +1790 | 0 | 0% |
| default | E0 | T4 | 18 | 0.000 | 17470 | +1784 | 0 | 0% |
| default | E1a | T1 | 12 | 1.000 | 26415 | +10729 | 17344 | 0% |
| default | E1a | T3 | 12 | 1.000 | 18730 | +3045 | 2553 | 0% |
| default | E1a | T4 | 18 | 1.000 | 29035 | +13349 | 22274 | 0% |
| default | E1b | T1 | 12 | 0.917 | 24724 | +9038 | 17344 | 0% |
| default | E1b | T3 | 12 | 1.000 | 17003 | +1317 | 2553 | 0% |
| default | E1b | T4 | 18 | 1.000 | 27321 | +11635 | 22274 | 0% |
| default | E2 | T1 | 12 | 0.830 | 17228 | +1543 | 2043 | 0% |
| default | E2 | T3 | 12 | 1.000 | 16378 | +692 | 632 | 0% |
| default | E2 | T4 | 18 | 0.722 | 17502 | +1816 | 2513 | 0% |
| default | E4 | T1 | 12 | 0.754 | 18412 | +2727 | 5891 | 0% |
| default | E4 | T3 | 12 | 1.000 | 16539 | +854 | 1610 | 0% |
| default | E4 | T4 | 18 | 1.000 | 19006 | +3320 | 7318 | 0% |

## Pareto view (score vs Δ context tokens, per model × family)

**default — T1**
- E2: score 0.830 at +1543 tok  ← frontier
- E0: score 1.000 at +1793 tok  ← frontier
- E4: score 0.754 at +2727 tok
- E1b: score 0.917 at +9038 tok
- E1a: score 1.000 at +10729 tok

**default — T3**
- E2: score 1.000 at +692 tok  ← frontier
- E4: score 1.000 at +854 tok
- E1b: score 1.000 at +1317 tok
- E0: score 1.000 at +1790 tok
- E1a: score 1.000 at +3045 tok

**default — T4**
- E0: score 0.000 at +1784 tok  ← frontier
- E2: score 0.722 at +1816 tok  ← frontier
- E4: score 1.000 at +3320 tok  ← frontier
- E1b: score 1.000 at +11635 tok
- E1a: score 1.000 at +13349 tok

