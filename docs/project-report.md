# Adaptive Self-Healing Software Engineer

## Project Report (B.Tech Final Year)

> Working document — results tables are filled from real benchmark runs.
> Marked **[VERIFY]** citations must be double-checked before submission.

---

## 1. Abstract

*(Fill in after the final experiment run — 2 paragraphs: task, motivation, method, headline result, conclusion.)*

## 2. Introduction

Automated program repair (APR) has moved from search-based techniques to
large-language-model (LLM) driven agents. State-of-the-art agents such as
AutoCodeRover and SWE-agent combine repository-level navigation, iterative
test execution, and patch generation to fix issues from real bug reports.
Despite progress, the **agent's knowledge is discarded after every session**:
a repair agent that failed on an issue is no better the second time it meets a
similar fault class.

This project studies a simple question:

> **Can persistent, repository-specific repair memory improve the effectiveness
> of LLM-based automated program repair?**

We extend an AutoCodeRover/ARISE-style agent with a persistent memory of past
repairs (issue category, affected functions, patch, tests, fault class) and
evaluate, on a synthetic benchmark of Python bugs, whether that memory
improves measurable outcomes compared to an identical agent without memory.

### 2.1 Problem statement

Given a repository and a bug report, build an autonomous agent that:

1. localizes the fault,
2. produces regression tests,
3. generates and verifies candidate patches in a sandbox,
4. revises on failure,
5. persists what it learned for future issues.

And, crucially, provide **evidence** (honest, reproducible A/B comparison)
about whether step 5 helps.

### 2.2 Contributions

1. A modular repair pipeline (analysis → graph → localization → test → patch → verify → memory)
2. Three comparable agent configurations (plain / graph-guided / graph+memory)
3. A deterministic benchmark of 10 buggy Python repos with known ground-truth fixes
4. An A/B evaluation framework with honest aggregate metrics and an honesty principle:
   *no simulated steps — every result comes from real repository clones, real
   patch application, and real sandboxed test execution.*

---

## 3. Literature Survey

### 3.1 LLM code repair

- **SWE-bench** benchmark and dataset — the standard for *issue → patch*
  evaluation over real GitHub issues (Jimenez et al., ICLR 2024;
  arXiv:2310.06770).
- **SWE-agent** — an agent-computer interface granting agents repository
  search, file edit, and test-run primitives so a model can solve SWE-bench
  issues interactively (Yang et al., NeurIPS 2024; arXiv:2405.15793).
- **AutoCodeRover** — an autonomous agent that structures exploration with
  AST-level program structures and issue-directed search, locally executing
  tests in a sandbox (Zhang et al., ICSE 2024; arXiv:2404.05427).
- **Agentless** — a simpler, two-phase (localization → patch) pipeline that
  reaches competitive SWE-bench results *without* an interactive editing
  interface, showing that structured context matters more than agent
  gymnastics (Xia et al., 2024; arXiv:2407.01489).

### 3.2 Repository-level graphs for code understanding

Several lines of work build repository-level code graphs (call graphs,
data-flow, dependency graphs) and feed LLMs graph-derived context:

- Hypothesis-driven fault localization with graph reasoning over **ARISE**-style
  data/control-flow relations **[VERIFY exact paper]**.
- **RepoGraph** — repository-scale code graphs to enhance retrieval and repair
  context for agents **[VERIFY** arXiv number**]**.
- Repository graphs built from ASTs (call, definition, reference relations)
  are standard in search systems and tool-chain guides (e.g., treesitter-based
  indexers). Our graph is a lightweight NetworkX multi-digraph with `CALLS`,
  `READS`, `WRITES`, `DEFINES`, and `REFERS` relations extracted without any
  static-analysis library.

### 3.3 Memory-augmented repair

The literature on copy/paste reuse, patch caching, and "repair libraries" is
sparse; most agent memory work targets conversational assistants rather than
repair pipelines. Our hypothesis extends the "self-evolving" idea: a repair
agent that stores *structurally similar resolved bugs* and surfaces them on
later issues.

---

## 4. Research Questions, Hypotheses

| ID | Question / Hypothesis |
|----|------------------------|
| RQ1 | Does repository-graph reasoning improve fault localization vs plain text? |
| RQ2 | **Does persistent memory improve repair performance on repeated issue classes?** |
| H1 | Memory increases first-attempt success (pass@1). |
| H2 | Memory reduces average attempts and regression-failure loops needed to fix. |
| H3 | Memory reduces total cost (tokens, wall-clock time). |
| H4 | Success rate is preserved (memory never makes repair worse on average). |

Null hypothesis (to be honest about): H1–H4 deltas are zero.

---

## 5. System Design

### 5.1 Pipeline

```
bug report + repo
   │
   ▼
[1] Clone          → fresh copy, local path or GitHub URL
[2] Analyze        → AST index: modules, classes, functions, tests
[3] Graph          → NetworkX multi-digraph (CALLS / READS / WRITES /
                     DEFINES) over functions & modules
[4] Issue analysis → category + keywords
[5] Memory query   → cosine-similar past repairs (proposed only)
[6] Localize       → graph-guided suspects (baseline2/proposed)
                      or keyword file matching (baseline1)
[7] Regression     → generate regression test, run against original
                      (expect FAIL = reproduced)
[8] Repair loop    → patch → apply → run tests in sandbox
                      → failure analysis → revise patch (≤ attempts)
                      → broken test? regenerate test
[9] Verify         → all tests pass on patched code
[10] Record        → store issue/patch/tests/fault-class + embedding
```

### 5.2 Agent configurations

| Config | Graph | Memory | Adaptive loop | Description |
|--------|:----:|:------:|:-------------:|-------------|
| baseline1 | ✗ | ✗ | ✓ | Plain LLM; keywords → file-level localization |
| baseline2 | ✓ | ✗ | ✓ | ARISE-style graph + full loop (**AutoCodeRover-like**) |
| proposed  | ✓ | ✓ | ✓ | baseline2 + persistent repair memory |

Only memory differs between baseline2 and proposed → the A/B comparison
`baseline2 vs proposed` isolates the memory effect.

### 5.3 Rationale for honest evaluation

- **Real execution**: patches are applied to real file copies; verification is
  real `pytest` in an isolated per-repo `uv` venv (Docker when available).
- **Honest memory**: retrieval is computed, not injected.
- **Stochastic agents**: LLM repair is random → we report per-run variance
  and repeat experiments.

*(Architecture diagram: see README sections or add a draw.io/mermaid export.)*

---

## 6. Experimental Setup

### 6.1 Benchmark

10 single-function Python bugs across 10 small repositories.
For each repo the ground-truth fix exists in the test suite: at least one test
asserts correct behaviour and **fails on the buggy code** (an oracle), while
other tests guard regression. The agent never sees the ground-truth fix.

| # | key | bug class | failing oracle(s) |
|---|-----|-----------|-------------------|
| 1 | discount-negative-qty | missing validation | 1 |
| 2 | csv-empty-input | null/empty handling | 1 |
| 3 | string-truncate-short | missing guard | 1 |
| 4 | taskboard-status-counts | wrong computation | 2 |
| 5 | flatten-list-descend | incomplete recursion | 2 |
| 6 | ratelimiter-window-reset | state not advanced | 1 |
| 7 | invoice-untaxed-items | wrong guard (tax) | 2 |
| 8 | textstats-trailing-newline | off-by-one | 1 |
| 9 | search-punctuation | validation/tokenization | 4 |
| 10 | url-fake-scheme | host validation | 1 |

### 6.2 Metrics (all computed from real runs)

- **success** — patched code passes every discovered test
- **pass@1** — success within the first repair attempt
- **avg_attempts** — repair attempts (incl. regenerated tests)
- **regression_failures_total** — failed attempts across all issues
- **avg_tokens** — LLM tokens per issue (cost proxy)
- **avg_duration_s** — wall-clock per issue

### 6.3 Procedure

```
Experiment A: proposed config with  use_memory = false   (10 issues)
Experiment B: proposed config with  use_memory = true    (10 issues)
(Re-run 3× for variance; report mean ± spread.)
```

Memory is cleared/persisted as in real deployment: Experiment A's successful
repairs populate memory that Experiment B retrieves.

---

## 7. Results

*(All values below are computed from real runs — see `GET /api/comparison`,
`storage/results/*.csv`, and the evaluations table.)*

### 7.1 Full Run (10 issues)

| metric | no memory (A) | with memory (B) | Δ |
|--------|:--:|:--:|:--:|
| success rate | 70% (7/10) | 70% (7/10) | 0.0 |
| pass@1 | 70% | 60% | −0.10 |
| avg attempts | 2.20 | 2.40 | +0.20 |
| regression failures | 22 | 24 | +2 |
| avg tokens | 5,084 | 6,692 | +1,608 |
| avg duration (s) | 189.0 * | 35.5 | −153.6 |

\* inflated by a single outlier: `csv-empty-input` took 1,660 s; without it A ≈ 25 s.

**Conclusion on the full benchmark: no measured benefit (or worse) — the null
hypothesis is NOT rejected.** This is an honest, reproducible outcome: at this
scale the memory signal is dominated by LLM stochasticity, and memory context
added tokens without consistently changing outcomes.

### 7.2 Small-sample ablation (4 issues, earlier run)

The same experiment on the initial 4-repo benchmark *did* show a memory
benefit — evidence that the effect, if any, is small and run-dependent:

| metric | no memory (A) | with memory (B) | Δ |
|--------|:--:|:--:|:--:|
| success rate | 100% | 100% | 0.0 |
| pass@1 | 25% | 50% | +0.25 |
| avg attempts | 2.25 | 1.50 | −0.75 |
| regression failures | 9 | 6 | −3 |
| avg tokens | 4,712 | 4,114 | −597 |
| conclusion | | | **memory helps** |

**Takeaway:** the measured effect is unstable across runs (LLM variance), so
more trials are needed before claiming H1–H3 hold.

### 7.3 Per-issue outcomes (10-issue runs)

| key | A (no mem) | B (mem) |
|-----|:--:|:--:|
| discount-negative-qty | ✓ (1) | ✓ (1) |
| csv-empty-input | ✗ (5) | ✓ (3) |
| string-truncate-short | ✓ (1) | ✓ (1) |
| taskboard-status-counts | ✓ (1) | ✓ (1) |
| flatten-list-descend | ✗ (5) | ✗ (5) |
| ratelimiter-window-reset | ✓ (1) | ✓ (1) |
| invoice-untaxed-items | ✓ (1) | ✓ (1) |
| textstats-trailing-newline | ✓ (1) | ✗ (5) |
| search-punctuation | ✓ (1) | ✓ (1) |
| url-fake-scheme | ✗ (5) | ✗ (5) |

✓ = fixed (attempts), ✗ = not fixed after ≤5 attempts.

`flatten-list-descend` and `url-fake-scheme` are consistently hard for the
agent in both configurations — useful qualitative data for §8.

### 7.4 Example repair transcript (rate-limiter, memory off)

```
tests      Regression test written: ['test_is_allowed_resets_window']
repair     Attempt 1: regression FAIL · existing 0 fail · 4 pass total
repair     Failure analysis: ... existing tests all passed ...
repair     Attempt 2: regression FAIL · existing 0 fail · 4 pass total
repair     Regression test disagrees with existing passing tests; regenerating it
tests      Regenerated regression test against original: 0 failing / 1 passing
repair     Attempt 3: regression PASS · existing 0 fail · 5 pass total
repair     Attempt 3 verified — all tests pass
```

The patch was correct at **attempt 1** (verified in storage); the agent's
self-written regression test asserted impossible/wrong semantics. The adaptive
loop regenerated the test once existing tests all passed, then verified the
**already-correct** patch — the revision loop fixed the *test*, not the code.
This failure mode (inverted regression test) was identified and mitigated
during development (§9 Threats).

---

## 8. Discussion

- **RQ1 (graphs)**: both baseline2 and proposed fix 7/10 — graph-guided
  localization produced accurate suspects on every issue
  (`top suspect` in the timeline matched the seeded bug), but contribution to
  end-to-end success is entangled with the repair loop itself.
- **RQ2 / H1–H4 (memory)**: NOT supported on the 10-issue run. Deltas were
  mixed (attempts +0.2, tokens +1.6k, pass@1 −0.1) while the 4-issue ablation
  favoured memory (attempts −0.75, pass@1 +0.25). Interpretation: any memory
  effect is currently smaller than LLM stochasticity. The honest conclusion —
  **"no measured benefit (or worse)"** — demonstrates the evaluation is
  disconfirmable rather than confirmatory by construction.
- **Consistently hard issues**: `flatten-list-descend` (list-recursion) and
  `url-fake-scheme` (host validation) failed in both conditions even with
  correct localization — the LLM produced valid but wrong patches (e.g.
  over-fitting the happy path), and no memory record could rescue it.
- **Test-generation failure mode**: the most impactful fragility was the
  agent's own regression tests, not the patches. One correct patch (rate-limiter)
  was nearly discarded because the regenerated test asserted impossible
  semantics; a "existing-pass ⇒ distrust regression test" rule fixed it.
- **Where memory could still help**: repeated, structurally identical issue
  classes (same repo, same function family) rather than one-shot novel bugs;
  also as a patch-reuse cache, which this round of bugs rarely triggered.

## 9. Threats to Validity

- **Internal**: bug set is synthetic; evaluation sample small; single LLM
  backend (see §3.2 of README for model config); stochasticity → need repeats.
- **External**: Python only; single-function/small repos; no real second-opinion
  benchmark (SWE-bench slice) yet.
- **Construct**: "memory helps" defined only on our chosen deltas; embedding
  quality depends on the hash fallback when the provider lacks an embeddings
  endpoint.
- **Conclusion**: metrics are over 10 issues; report statistical spread, not
  just point estimates.

## 10. Conclusion and Future Work

- The system works end-to-end: real repairs, real sandboxed verification, real
  memory persistence, real (and disconfirmable) A/B metrics over 10 varied bugs.
- **On the primary hypothesis, the null is not rejected**: memory neither
  clearly helped nor hurt on the full run, and signaled a benefit only on a
  smaller ablation. This is a valid, reportable result — APR memory effects are
  evidently small relative to agent stochasticity at this scale.
- **Secondary contributions hold**: graph-guided localization was consistent;
  the adaptive loop (revise patch or revise test based on which signal is
  unreliable) materially improved outcomes on hard-to-reproduce issues.
- Future work: a SWE-bench Verified (Python) slice for external validity;
  repeated-issue-class evaluation to test memory where it is theoretically
  strongest; memory consolidation and forgetting; multiple LLM backends and
  repeated trials (3×) with statistical spread; cross-language support.

---

## 11. References

1. Jimenez, C. E., et al. *SWE-bench: Can Language Models Resolve Real-World GitHub Issues?* ICLR 2024. arXiv:2310.06770.
2. Yang, J., et al. *SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering.* NeurIPS 2024. arXiv:2405.15793.
3. Zhang, Y., et al. *AutoCodeRover: Autonomous Program Improvement.* ICSE 2024. arXiv:2404.05427.
4. Xia, C., et al. *Agentless: Demystifying LLM-based Software Engineering Agents.* 2024. arXiv:2407.01489.
5. ARISE — graph-guided repair approach referenced in this project's prior art. **[VERIFY paper + authors]**
6. Hu, Y., & Li, T. *RepoGraph: Enhancing AI Software Engineering with Repository-level Code Graph.* **[VERIFY arXiv number]**
7. *(Add: any LLM-repair survey, e.g. Fan et al., "Automated Code Repair with LLMs" —* **[VERIFY]** *)*