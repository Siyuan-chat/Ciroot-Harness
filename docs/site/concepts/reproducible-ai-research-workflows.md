---
title: Reproducible AI research workflows
description: Reproducible AI research freezes important inputs, preserves source and evidence identity, records failures, and keeps review decisions with the run.
---

# Reproducible AI research workflows

A **reproducible AI research workflow** preserves the inputs and research state needed to understand or repeat a result later. Reproducibility does not require every external source to remain unchanged forever; it requires the system to record which versions, queries, configuration, evidence, and decisions were used for the run.

## What needs to be frozen or persisted?

Useful research records include:

- the research specification and its revision;
- non-secret runtime/configuration metadata;
- reference-set identity;
- source and query attempts;
- document and document-version identities;
- evidence locators;
- structured findings;
- human-review events;
- final run status;
- exported report artifacts.

Secrets such as API keys should not be embedded into the reproducibility record.

## Why “same prompt” is not enough

Repeating a prompt does not reproduce a research run if the source corpus, retrieval result, document version, or model/tool configuration changed.

A more useful model is:

```text
frozen inputs
+ recorded retrieval
+ versioned sources
+ evidence identities
+ review history
= inspectable research run
```

This also makes it possible to distinguish a **new result caused by new evidence** from a result that merely changed because the wording of a model response changed.

## CirootHarness's approach

CirootHarness treats frozen run inputs, persistent source/evidence records, explicit outcome states, and review history as first-class research artifacts.

The deterministic Golden Demo provides a bounded example that can be executed offline and reopened. Because one synthetic source is intentionally malformed, the repeatable expected state is `partial`. Reproducibility includes reproducing the limitation rather than hiding it.

## Reproducible does not mean identical forever

Real APIs, web sources, and model providers change. A reproducible system should therefore record enough provenance to explain those changes and distinguish the historical run from a later rerun.

CirootHarness stores historical artifacts rather than silently rewriting old research outputs when a later workflow changes.

---

**Last verified:** 2026-10-05  
**Public preview reference:** v0.1.2-desktop-preview  
**Worked example:** [Golden Demo](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/GOLDEN_DEMO.md)
