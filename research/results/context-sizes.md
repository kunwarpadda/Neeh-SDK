# Context sizes (offline, exact)

S0 corpus, 12 pages. Visual tokens use Claude's 28x28-patch rule
(1836 per full-page PNG). Text-token costs come from the live
sweep ledger, not from characters — this table is the model-free exhibit.

| arm | page kind | pages | mean strokes | mean context chars | mean PNG bytes | visual tokens |
|---|---|---|---|---|---|---|
| E0 | shapes | 6 | 5 | 0 | 24,340 | 1836 |
| E0 | text | 6 | 74 | 0 | 39,669 | 1836 |
| E1a | shapes | 6 | 5 | 2,553 | 24,340 | 1836 |
| E1a | text | 6 | 74 | 32,135 | 39,669 | 1836 |
| E1b | shapes | 6 | 5 | 2,553 | 0 | 0 |
| E1b | text | 6 | 74 | 32,135 | 0 | 0 |
| E2 | shapes | 6 | 5 | 632 | 0 | 0 |
| E2 | text | 6 | 74 | 3,453 | 0 | 0 |
| E3 | shapes | 6 | 5 | 856 | 0 | 0 |
| E3 | text | 6 | 74 | 3,273 | 0 | 0 |
| E4 | shapes | 6 | 5 | 1,610 | 0 | 0 |
| E4 | text | 6 | 74 | 10,171 | 0 | 0 |
| E5 | shapes | 6 | 5 | 329 | 0 | 0 |
| E5 | text | 6 | 74 | 2,626 | 0 | 0 |
| E6 | shapes | 6 | 5 | 0 | 23,724 | 1836 |
| E6 | text | 6 | 74 | 0 | 53,350 | 1836 |
| E7 | shapes | 6 | 5 | 722 | 24,340 | 1836 |
| E7 | text | 6 | 74 | 4,025 | 39,669 | 1836 |
| E7v | shapes | 6 | 5 | 722 | 0 | 0 |
| E7v | text | 6 | 74 | 4,025 | 0 | 0 |

Reading: E1a/E1b carry the ICF v0 JSON — compare their context chars against
E0's zero chars + 1836 visual tokens, and against E2/E4's compressed text.
A conservative 4-chars-per-token reading is indicative only; the ledger's
model-reported input tokens are the number that counts.
