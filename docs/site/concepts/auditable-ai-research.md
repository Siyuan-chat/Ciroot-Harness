---
title: What is an auditable AI research agent?
description: An auditable AI research system preserves research inputs, retrieval attempts, source-linked evidence, review decisions, and explicit completion states.
---

# What is an auditable AI research agent?

An **auditable AI research agent** is a research system whose important inputs, retrieval actions, evidence, intermediate decisions, and final claims can be inspected after the model finishes. The goal is not merely to produce fluent prose. It is to preserve enough structured state that a reviewer can ask **what was searched, what was found, what failed, what evidence supports a claim, and what remains uncertain**.

CirootHarness uses the term **research harness** because these audit properties depend on deterministic storage, identity, validation, and review mechanisms around the model—not only on the model's reasoning.

## What makes research auditable?

A practical auditable workflow usually needs several independent properties:

1. **Versioned requirements.** The research question, scope, criteria, and constraints should be frozen for a run.
2. **Recorded retrieval attempts.** A failed source or exhausted query should remain visible rather than disappearing from the report.
3. **Stable source identity.** Evidence should point to a particular document version, not only to a title or URL string.
4. **Evidence locators.** Important claims should map back to a page, paragraph, XML location, or other inspectable source position when available.
5. **Explicit outcome states.** `partial`, `failed`, and `unsupported` should not be rewritten as `completed`.
6. **Human review history.** Ambiguity and unresolved evidence gaps should be reviewable and persist across reopen/re-run flows.

## How CirootHarness models this

CirootHarness preserves a versioned `ResearchSpec`, source/query attempts, document and document-version identities, evidence records, claim-to-evidence references, review issues, and run outcomes.

A simplified trace looks like this:

```text
research question
  -> frozen ResearchSpec
  -> source/query attempt
  -> document version
  -> evidence + locator
  -> claim
  -> review state
  -> report + final run status
```

The [deterministic Golden Demo](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/GOLDEN_DEMO.md) provides a reproducible synthetic example. It intentionally contains one malformed synthetic document, so its expected final state is `partial`. That is deliberate: the demo is designed to show that an incomplete source path stays visible.

## What does auditable not mean?

Auditable does **not** mean infallible.

An audit trail can reveal where a model or retrieval system made a weak decision; it does not automatically make every scientific or patent conclusion correct. Scientific validity, search coverage, and legal interpretation require their own evaluation.

For CirootHarness, the current public boundary is summarized in [Current status](../current-status.md). Live patent research is still being integrated and should not be interpreted as complete production coverage or as a legal-opinion service.

## Why this matters

For research work, the cost of a plausible but untraceable answer can be higher than the cost of an explicit `partial` result. An auditable system makes uncertainty inspectable and gives a reviewer a concrete path back to the underlying evidence.

---

**Last verified:** 2026-10-05  
**Public preview reference:** v0.1.2-desktop-preview  
**Engineering source of truth:** [DEVELOPMENT_STATUS.md](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/DEVELOPMENT_STATUS.md)
