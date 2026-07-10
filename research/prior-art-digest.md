# Prior-Art & Feasibility Digest

Research inputs for the ICF representation program. Compiled 2026-07-09 from a web sweep;
each claim links its source. This feeds the M0 research protocol.

## 1. Prior art: can models perceive stroke data as text?

### Directly on-thesis

**Google — "Representing Online Handwriting for Recognition in Large Vision-Language Models"
([arXiv 2402.15307](https://arxiv.org/abs/2402.15307)).** The closest existing work to the ICF
thesis, and it *validates the core bet*: digital ink rendered as discrete text tokens is readable
by VLMs. Their pipeline: resample points at fixed 20 ms intervals → scale-normalize coordinates →
encode as **relative offsets** (dx, dy) → round to integers → emit as `<stroke> x y x y …` with no
explicit time values. This cut the median sample from 2,692 tokens (raw x,y,t) to **367 tokens**.
Key ablation: **ink-as-text alone (4.64% CER) beat image-only (8.07% CER)**; combined was best
(4.55%). Caveat that defines Neeh's research gap: these were *fine-tuned* small VLMs (PaLI 700M,
PaLM-E 500M). Whether **zero-shot frontier models** can read such encodings is the open question —
that is the experiment Neeh can own.

**SketchAgent — MIT CSAI/Stanford, CVPR 2025 ([arXiv 2411.17673](https://arxiv.org/abs/2411.17673),
[project page](https://sketch-agent.csail.mit.edu/)).** Off-the-shelf pretrained multimodal LLMs,
**no fine-tuning**, draw recognizable sketches through a textual "sketching language": a numbered
1–50 grid canvas, strokes as coordinate-cell sequences, smoothed into Bézier curves at render
time, taught entirely by in-context examples. Proof that pretrained multimodal LLMs can manipulate
stroke coordinates zero-shot **when the encoding is friendly (small-integer grid, in-context
legend)**. They generate; Neeh asks the converse (perceive + edit) — same representational
machinery.

**ScribeTokens ([arXiv 2603.02805](https://arxiv.org/pdf/2603.02805), 2026).** Fixed-vocabulary
tokenization of digital ink: quantized coordinate bins plus pen-down/pen-up/movement event tokens,
designed to plug ink into pretrained LMs. Competitive with continuous-coordinate models. Signal:
the field is converging on ink tokenization *right now* — timing is right, and nobody owns the
"agent context + addressable editing" angle.

### Encoding-design evidence

**VGBench — EMNLP 2024 ([arXiv 2407.10972](https://arxiv.org/abs/2407.10972),
[site](https://vgbench.github.io/)).** LLMs on vector-graphics understanding/generation across
formats: they do markedly **better on higher-level semantic formats (TikZ, Graphviz) than raw SVG
paths**; chain-of-thought prompting helps the low-level cases. Implication: ICF encodings should
climb the abstraction ladder — grouped/semantic representations are not a nice-to-have, they are
where models are strongest.

**VDLM — "Visually Descriptive Language Model for Vector Graphics Reasoning"
([arXiv 2404.06479](https://arxiv.org/abs/2404.06479),
[project](https://mikewangwzhl.github.io/VDLM/)).** Raster → SVG → "Primal Visual Description"
(text records of primitives: shape, position, measurements) → zero-shot LLM reasoning. **Beats
GPT-4V on precise low-level tasks** (angle classification, length comparison, maze solving).
Strong zero-shot evidence that *structured text primitives beat pixels for precise spatial
reasoning*. PVD is a cousin of ICF's `semantics` layer.

**InkFM ([arXiv 2503.23081](https://arxiv.org/html/2503.23081v1)).** Foundation model for
full-page ink (PaliGemma-3B, 45.6M samples): notably encodes ink as a **rendered image with
temporal dynamics in color channels** (red = time progression, green/blue = velocity). SOTA
full-page segmentation and multi-script recognition. Two takeaways: (a) a "temporal raster" is a
legitimate hybrid encoding for our matrix; (b) full-page structure (segmentation into text/drawing
regions) is what foundation models find hardest — matching VGBench's high-level > low-level story.

**InkSight — Google ([arXiv 2402.05804](https://arxiv.org/html/2402.05804v4),
[blog](https://research.google/blog/a-return-to-hand-written-notes-by-learning-to-read-write/)).**
The inverse problem — photos of handwriting → stroke sequences (ViT + mT5; 87% valid tracings on
HierText). Validates strokes as the canonical form worth recovering, and is a practical tool: it
could derender scanned/photographed notes into Neeh documents to grow a corpus.

### Known model weaknesses to design around

2025 spatial-reasoning surveys ([EmergentMind overview](https://www.emergentmind.com/topics/spatial-reasoning-in-llms),
[grid-reasoning dataset](https://arxiv.org/pdf/2603.17333)): LLMs exceed **80% on local primitive
recognition but stay under 50% on global integration** of piecemeal spatial facts into a coherent
map. Anthropic's own docs flag coordinate/localization outputs as approximate
([vision docs](https://platform.claude.com/docs/en/build-with-claude/vision)). Benchmark design
consequence: tasks must separate **local perception** (read one stroke/word) from **global layout**
(what's where, what overlaps), and grouped/scene-graph encodings are the specific bet for closing
the global gap.

## 2. Datasets: online-ink corpora with true stroke data

| Dataset | Content | Format | License | Notes |
|---|---|---|---|---|
| [Quick, Draw!](https://github.com/googlecreativelab/quickdraw-dataset) | 50M sketches, 345 categories | ndjson; strokes as `x[], y[], t[]` (raw) or RDP-simplified ε=2.0, 256×256, no timing | **CC BY 4.0** (permissive) | Best first corpus: license + trivial mapping to Neeh points |
| [MathWriting](https://github.com/google-research/google-research/blob/master/mathwriting/README.md) ([paper](https://arxiv.org/abs/2404.10690)) | 230k human + 400k synthetic math expressions → LaTeX | InkML | CC **BY-NC**-SA 4.0 | Largest online HME corpus; research-only |
| [IAM-OnDB](https://fki.tic.heia-fr.ch/databases/iam-on-line-handwriting-database) | ~86k English word instances, 200+ writers (whiteboard) | XML strokes with timestamps | Registration, research use | The canonical online-handwriting benchmark |
| [CROHME](https://www.iapr-tc11.org/mediawiki/index.php/CROHME:_Competition_on_Recognition_of_Online_Handwritten_Mathematical_Expressions) ([Zenodo 2023](https://zenodo.org/records/8428035)) | ~9k train + competition test sets, math | InkML with **symbol-level stroke segmentation** | CC BY-NC-SA 3.0 | Ground-truth stroke↔symbol groupings enable *addressing* tasks on real data |

License picture: all four are fine for a research benchmark; only Quick, Draw! is permissive
enough to redistribute fixtures with the SDK. This confirms the **synthetic-first** corpus
strategy (Neeh-generated ink = perfect labels, no licensing), with real corpora as validation.

## 3. Token economics (verified 2026-07)

Claude prices images in 28×28-px patches: `⌈w/28⌉ × ⌈h/28⌉` visual tokens
([vision docs](https://platform.claude.com/docs/en/build-with-claude/vision)).

- A full Neeh page rendered 1:1 (1000×1414) = 36 × 51 = **~1,836 visual tokens**, regardless of
  how much ink is on it. An empty page costs the same as a full one.
- Google's tokenized-ink pipeline reached a **median ~367 text tokens per handwriting sample**
  (relative offsets, integer quantization, time resampling) — roughly 5× cheaper than the page
  raster, and it *scales with content, not area*.
- **ICF v0's own vector record is likely more expensive than the PNG it accompanies**: 12 sampled
  points × 6 absolute floats plus record boilerplate ≈ 60–80 tokens per stroke → an 80-stroke page
  ≈ 5–6k tokens, versus ~1.8k for the raster. Back-of-envelope, to be measured precisely in M1 —
  but it means quantization/relative encoding isn't an optimization, it's the difference between
  the vector channel losing and winning on cost.

## 4. What this changes in the research program

1. **H1 sharpens.** "Structured ink can beat raster" is already demonstrated *with fine-tuning*
   (Google 2402.15307). Neeh's ownable question: **which encodings work zero-shot on frontier
   models, at what token budget, for perception *and* addressable editing.** Nobody in the prior
   art does the editing half — recognition only. Stable stroke IDs + act-on-ink tasks are the
   novel benchmark contribution.
2. **The encoding matrix is now evidence-based:** (a) ICF v0 as-is (baseline/control);
   (b) quantized relative-offset polylines (Google recipe); (c) small-integer grid language
   (SketchAgent recipe); (d) SVG path text (VGBench low-level control); (e) PVD-style described
   primitives / grouped scene graph (VGBench + VDLM says this should win global tasks);
   (f) temporal raster — time/velocity in color channels (InkFM) — as the hybrid arm.
3. **Task suite must split local vs global** perception (models are >80% local, <50% global), and
   include addressing ("which stroke IDs form X?") and action grounding (edit correctness), where
   vector context has no raster substitute.
4. **Corpus order:** synthetic Neeh-generated → Quick, Draw! (CC BY) → CROHME (addressing tasks
   with real segmentation ground truth) → IAM-OnDB / MathWriting (validation).
