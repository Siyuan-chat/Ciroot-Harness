---
title: Research agent vs research harness
description: A research agent performs model-driven research tasks; a research harness adds deterministic state, evidence identity, validation, review, and reproducibility around those tasks.
---

# Research agent vs research harness

A **research agent** usually refers to a model-driven worker that plans or executes research tasks. A **research harness** is the surrounding system that makes those tasks bounded, persistent, inspectable, and reproducible.

The terms can overlap, but the distinction is useful:

| Research agent | Research harness |
| --- | --- |
| Plans and performs model-driven tasks | Defines the environment and contracts those tasks operate within |
| May optimize for the final answer | Preserves the process and evidence behind the answer |
| Often works in conversational context | Persists stable run/document/evidence/review state |
| Can choose tools or queries | Records tool/source attempts and budgets |
| Produces interpretations | Links claims to evidence and review state |
| May stop when prose is produced | Tracks explicit completion and unresolved work |

## Why the harness matters

A model can be highly capable while still operating in a fragile research workflow. Without durable state, later reviewers may not be able to reconstruct:

- the exact research requirements;
- the queries that were attempted;
- the version of a source that was read;
- the evidence behind a claim;
- the reason an item was excluded;
- or whether a source failure reduced coverage.

The harness makes these properties part of the product contract instead of leaving them inside transient model context.

## Where CirootHarness fits

CirootHarness includes model/agent roles in its target and integrated architecture, but its defining layer is the persistent research harness around them.

The design emphasizes:

- versioned `ResearchSpec` inputs;
- source/query accounting;
- durable document and evidence identities;
- claim-to-evidence links;
- explicit `complete` / `partial` / `failed` / `unsupported` states;
- human-review history;
- reproducible artifacts.

This is why the project describes itself as an **auditable AI research harness**, not simply another answer-generation agent.

## Which should you choose?

If the only goal is a quick exploratory answer, a lightweight research agent may be sufficient.

If the result must later be reviewed, reproduced, challenged, handed off, or connected to a technical record, a harness-style architecture becomes more important.

---

**Last verified:** 2026-10-05  
**Related docs:** [System design](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/SYSTEM_DESIGN.md) · [Architecture](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/ARCHITECTURE.md)
