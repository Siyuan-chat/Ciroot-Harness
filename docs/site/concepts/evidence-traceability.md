---
title: Evidence traceability in AI research
description: Evidence traceability connects AI-generated claims to document versions, source excerpts, and inspectable source locations.
---

# Evidence traceability in AI research

**Evidence traceability** means that a research claim can be followed back through a stable evidence record to the specific source material that supports it. A citation string alone is not enough if the cited document, version, excerpt, or location cannot be recovered and checked.

For AI-assisted research, a useful trace is closer to:

```text
claim
  -> evidence ID
  -> document version
  -> excerpt / quote
  -> source locator
  -> original or normalized source record
```

## Why citations are not the same as evidence

A model can produce a syntactically valid DOI, URL, or bibliography entry without proving that the cited source supports the sentence beside it. Traceability therefore needs to separate several questions:

- Does the referenced document exist?
- Which version of the document was analyzed?
- What exact passage or structured field was used?
- Where is that passage located?
- Does the evidence actually support the claim?
- Was the claim later revised or sent to human review?

These are different checks and should not be collapsed into one “has citation” flag.

## The CirootHarness evidence model

Within its accepted scope, CirootHarness records evidence against a document version and a locator, and report claims reference evidence identities rather than relying only on free-form citation text.

The public project principle is:

> A citation is not evidence until it can be traced back to the source.

The system also keeps source/query attempts and explicit run states so a verified claim is not confused with complete search coverage.

## A concrete example

The public Golden Demo uses synthetic documents and a deterministic workflow. A report claim can be reopened through its evidence reference to the stored source identity and locator. The same demo intentionally retains an unresolved normalization problem instead of smoothing it into the final prose.

That example demonstrates **trace mechanics**, not real-world scientific accuracy or exhaustive patent coverage.

## Evidence quality still matters

Traceability makes evidence inspectable; it does not guarantee that the evidence is sufficient or that the interpretation is correct. A weak source can be perfectly traceable and still be weak evidence.

A robust research workflow therefore needs both:

- **mechanical traceability** — identities, versions, locators, persisted excerpts; and
- **semantic review** — whether the evidence actually supports the scientific or technical claim.

CirootHarness records the former and provides review primitives for the latter. Exact accepted boundaries are maintained in the project's [engineering status](../current-status.md).

---

**Last verified:** 2026-10-05  
**Public preview reference:** v0.1.2-desktop-preview  
**Related implementation docs:** [Contracts](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/CONTRACTS.md) · [Golden Demo](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/GOLDEN_DEMO.md)
