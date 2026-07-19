# V4 HONEST REMAINING WALLS — Eagle Eye Zenith

Supersedes the walls sections of every prior receipt set (see
RECEIPT_STATUS_INDEX.md). Resolved walls are listed with their closing
evidence; open walls are stated plainly with no softening.

## Closed in V4 (evidence cited)

- **W3 (open since V1) — browser gate not executed** → **CLOSED.**
  Headless Chromium (Playwright) now drives the real cockpit against the real
  local server: supplier selection, evidence trace, in-browser WebCrypto
  commitment recomputation, evolution lineage/budget/rejection/final-audit,
  fixture + external-action labeling; zero JS errors, zero failed requests
  (`scripts/browser_verification.py`, receipt + screenshot in
  artifacts/browser/latest/). Remaining minor: exercised on one engine
  (Chromium fallback build for this OS); no cross-browser matrix.
- **V3 evaluator-secret defect** (`evaluator-secret-{live_seed}-{code_revision}`)
  → **CLOSED.** CSPRNG operator boundary, commitment binds secret+provenance,
  irreversible INITIALIZED→EVALUATING→FINALIZED→REVEALABLE lifecycle, early
  reveal hard-fails, regression grep test.
- **V3 uncharged failed looks** → **CLOSED.** Charge-before-execution with
  terminal statuses; the audit's 3-nonce adversarial capture probe passes
  (3 charges, 3 FAILED results, no target truth in captured inputs).
- **V3 partial "full decision replay"** → **CLOSED.** Real full-decision
  replay (33 checks) + 19/19 mutation battery + non-vacuous CLI fixture.
- **V3 "power tripled" mislabeling** → **CLOSED** by withdrawal + measurement:
  stratum-preserving independent resampling; measured Type-I 0.000–0.005 vs
  allocated 0.0025; power ≈0.90/0.96 (scale 1/3) at −0.02 nats
  (MODEL_CONDITIONAL_ESTIMATE).
- **V3 version/provenance mismatch** → **CLOSED.** Single imported
  EVALUATOR_VERSION; mandatory lock digest; make setup installs the exact
  audited pin set; pip check clean.
- **V2/V3 incomplete archives with stale roots** → **CLOSED.** V4 archive
  contains all 113 PNGs under root EAGLE_EYE_ZENITH_FABLE_HANDOFF_V4; manifest
  passes from clean extraction; path-safety verified.

## Open walls (V4, stated plainly)

- **W1 — No neural transformer was trained.** The candidates remain
  algorithmic empirical-Bayes analogs of the paper's architectures behind the
  same interface. No GPU/PyTorch here. Scale-up path unchanged
  (`predict_neural(compiled)` behind `_package()`).
- **W2 — Everything is synthetic.** Both generator families are synthetic.
  There is NO live-data evidence anywhere in this repo. EXTERNALLY VALIDATED:
  nothing.
- **W-org — Evaluator independence is a software boundary in ONE process.**
  Name-mangling, charged access, and commit-reveal are MECHANICALLY VERIFIED
  at the API level; organizational/host isolation is NOT ESTABLISHED and
  cannot be established inside a single process by construction. In-process
  Python cannot stop a candidate from CAPTURING its inputs — V4 makes every
  capture cost a charged, signed, terminal-status look and keeps target truth
  on the other side of the boundary; it cannot do more than that in-process.
- **W-kms — Ephemeral in-run Ed25519 demo keys.** Registry-pinned, but no
  production KMS/HSM custody. NOT ESTABLISHED.
- **W-confounding — No sensitivity model for unobserved confounding.**
  Off-policy identifiability is measured (overlap, ESS, recomputed
  propensities) but sensitivity to unobserved confounders is NOT ESTABLISHED.
- **W-transfer — Champion advantage does NOT survive a structurally
  independent generator.** Measured finding (100 precommitted seeds): NLL
  CI95 [-0.024, +0.042], per-seed failure rate 0.49. Calibration held
  (coverage 0.888, in band) — the governor's trust properties transfer; the
  accuracy advantage does not. Under the in-family shift, NLL transfer holds
  but CRPS transfer does not (CI95 [-0.004, +0.031]). Any "robust transfer"
  claim is therefore NOT ESTABLISHED beyond in-family NLL.
- **W-promotion — promotions are rare, small, and per-run.** Most runs end
  NO_CHALLENGER_EARNED_PROMOTION. The first rule-passing promotion (run
  `sevo4-51a4e71deb16`) was a single whitelist parameter
  (`governor.shift_suspect_milli` 800→900) with mean effect −0.0171 nats and
  a one-sided CI upper bound of −0.00025 — borderline significance, fully
  replay-verified. At alpha_per_look=0.0025 a false-positive look is possible
  across accumulated looks; treat any single borderline promotion as
  provisional evidence, not a trend. Structural (non-whitelist) improvements
  still require human governance by design.
- **W-crossrun — cross-run alpha is not pooled.** Each run controls FWER
  across its OWN looks (Bonferroni). Fresh CSPRNG suites per run mean an
  operator could in principle re-run until a borderline promotion appears
  ("rerun lottery"). The guard is procedural and auditable, not statistical:
  every run appends to the receipt/epoch ledger, so the number of runs
  preceding any adopted promotion is visible. Pooled cross-run alpha
  accounting is future work; until then, adoption decisions must cite the
  full run history.
- **W-timeout — TIMED_OUT looks use SIGALRM**, which works only on the main
  thread; off-main-thread callers get exception-based FAILED accounting but
  no wall-clock kill (documented in sealed_evaluator).
- **W-power-model — The power analysis is MODEL_CONDITIONAL** (bootstrap over
  an empirical null from one synthetic generator); it is not a guarantee
  about live effect distributions.
- **W-canonical — The canonical repository** (`/Users/Apple/Projects/
  eagle-eye-zenith`, base 46f6e2f) **was not touched** — it is not reachable
  from this environment by construction. Nothing here is merged; this archive
  is candidate work awaiting local verification.
