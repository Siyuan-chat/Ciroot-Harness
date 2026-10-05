---
title: CirootHarness glossary
description: Plain-language definitions of the core concepts used by CirootHarness and auditable AI research workflows.
---

# Glossary

## Auditable AI research

AI-assisted research whose important inputs, retrieval actions, source evidence, decisions, limitations, and outputs remain inspectable after generation.

## Evidence

A persisted source-backed record used to support or challenge a research claim. In CirootHarness, evidence is associated with source identity/version and a locator rather than being only a bibliography string.

## Evidence traceability

The ability to follow a claim back through an evidence identity to the source material and location that supports it.

## Research agent

A model-driven worker or role that plans, retrieves, analyzes, verifies, synthesizes, or writes within a research workflow.

## Research harness

The deterministic application layer around model-driven research: specifications, identities, storage, retrieval accounting, budgets, validation, evidence links, review state, and outputs.

## ResearchSpec

The versioned structured representation of a research request used to define and freeze the scope of a run.

## Document version

The specific content version of a source analyzed by a run. A stable document identity and a content version are related but not interchangeable.

## Locator

A position that helps a reviewer reopen the relevant source evidence, such as a page, paragraph, section, or structured XML location when available.

## Local RAG

Retrieval-augmented generation infrastructure in which the controlled corpus and retrieval index are kept locally. Local retrieval does not automatically imply that model inference is local.

## Reference corpus

A controlled set of source documents used as an explicit research baseline. CirootHarness separates reference material from newly discovered material.

## Discovery material

New source material retrieved during an investigation. Discovery material does not automatically become part of the frozen reference baseline.

## `partial`

A run state indicating that useful work or supported conclusions exist but the required coverage or workflow did not complete fully.

## `failed`

A run state indicating that the intended operation did not produce a usable completed result.

## `unsupported`

A state indicating that a requested capability or source path is not supported in the current configuration or implementation boundary.

## Human review

A persistent issue/decision path for ambiguity, evidence gaps, conflicts, or other cases that should not be silently converted into model certainty.

---

For current implementation boundaries, see [Current status](current-status.md).
