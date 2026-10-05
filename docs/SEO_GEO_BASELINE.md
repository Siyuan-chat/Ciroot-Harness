# CirootHarness SEO / GEO baseline

Date: 2026-10-05

This file is the public implementation baseline for repository discovery, search-engine optimization (SEO), and generative-engine optimization (GEO). It does not change product capability claims. The accepted implementation boundary remains defined by [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) and stage-specific acceptance records.

## 1. Canonical entity

Use these names consistently:

| Surface | Canonical value | Notes |
| --- | --- | --- |
| Product | **CirootHarness** | Public product/entity name |
| GitHub repository | **Siyuan-chat/Ciroot-Harness** | Canonical code repository |
| Python distribution | `research-harness` | Implementation/package name; not a second product |
| Desktop executable | `ResearchHarnessGUI.exe` | Compatibility name retained for the preview |
| Product category | **auditable AI research harness** | Primary descriptive category |
| Primary domains | **patent research** and **scientific literature** | Do not imply complete live patent coverage |

Historical references may preserve earlier repository names when they are part of immutable stage records. Active navigation, citation metadata, release links, and new public copy should use the canonical repository.

## 2. Canonical one-sentence description

Preferred public description:

> CirootHarness is an open-source, local-first and auditable AI research harness for patent research and scientific literature, built around evidence traceability, reproducibility and explicit review states.

Short GitHub repository description:

> Open-source, local-first and auditable AI research harness for patent research and scientific literature, with evidence traceability, local RAG and MCP.

The short description should be used for GitHub repository metadata when repository settings are updated.

## 3. Recommended GitHub topics

Recommended topic set:

- `research-agent`
- `research-harness`
- `patent-research`
- `patent-search`
- `scientific-literature`
- `literature-review`
- `rag`
- `local-rag`
- `evidence-traceability`
- `auditable-ai`
- `reproducible-research`
- `ai4science`
- `mcp`
- `langgraph`
- `openalex`
- `research-automation`

Do not add `freedom-to-operate`, `patentability-search`, or similar legal/outcome-oriented topics until the corresponding live workflow and semantic acceptance explicitly support those claims.

## 4. Homepage policy

Until a dedicated public documentation site exists, do not point the repository homepage to the local GUI or to a placeholder site.

Planned canonical documentation surface:

- static public documentation site;
- stable canonical URLs;
- sitemap and robots policy;
- Open Graph metadata;
- structured data where appropriate;
- multilingual navigation;
- answer-oriented pages for high-value research questions.

The documentation-site implementation is a separate stage and must not be marked complete by this repository-metadata baseline.

## 5. Social preview policy

The repository social preview must use a **real screenshot from the reproducible public demo**, not a synthetic UI mockup.

Target format:

- 1280 × 640;
- CirootHarness logo/name;
- headline: **Auditable AI research for patents & scientific literature**;
- one real product screenshot crop;
- footer: **Evidence-linked · Local-first · Reviewable**.

The screenshot and preview image remain pending until the public demo capture requirements in [DEMO_SHOWCASE.md](DEMO_SHOWCASE.md) are satisfied.

## 6. Search-intent vocabulary

Use these concepts naturally in public pages. They are descriptive vocabulary, not a keyword-stuffing checklist.

### Brand queries

- CirootHarness
- Ciroot Harness
- CirootHarness GitHub
- CirootHarness research harness

### Category queries

- open source patent research agent
- auditable AI research agent
- evidence traceable research agent
- scientific literature research agent
- local RAG for scientific literature
- reproducible AI research workflow
- open source AI research harness
- research agent with evidence verification

### Question-style GEO queries

- What is an auditable AI research agent?
- What tools can trace AI-generated research claims back to source evidence?
- What open-source tools support reproducible AI research?
- What is the difference between a research agent and a research harness?
- What open-source software combines patent research and scientific literature workflows?

Public content should answer the underlying question directly and then describe which parts CirootHarness currently implements.

## 7. GEO answer format

High-value public explanation pages should normally contain:

1. a direct one-paragraph answer;
2. key concepts and definitions;
3. an architecture or workflow explanation;
4. a concrete worked example;
5. links to implementation or acceptance evidence;
6. current limitations;
7. last-verified date and relevant version.

The aim is to make claims easy to inspect and cite. A page must not remove uncertainty merely to sound authoritative.

## 8. Benchmark

Track the following separately:

| Dimension | Check |
| --- | --- |
| Brand indexing | Does a search for CirootHarness resolve to the canonical repository/site? |
| Non-brand discovery | Does the project appear for relevant category/problem queries? |
| Generative mention | Do answer engines identify CirootHarness for an appropriate question? |
| Generative citation | Do answer engines cite the repository/docs rather than only mention the name? |
| Conversion | Repository visits, stars/forks, release downloads, docs referrals |

A baseline check should record the query, engine, date, result position/mention, cited URL, and whether the cited claim matches the current acceptance boundary.

## 9. Current implementation status

As of this baseline:

- canonical product and repository names are defined;
- active README navigation is being aligned to the canonical repository;
- three-language README discovery copy is being optimized;
- `CITATION.cff` is being aligned to the canonical repository;
- GitHub repository topics and repository-description settings are **recommended but not automatically applied by the current connector**;
- a repository social preview is **pending a real reproducible demo screenshot**;
- a dedicated SEO/GEO documentation site, structured data, sitemap, crawler policy, and answer pages are later construction stages.

Do not convert the two pending items above into completion claims without verifying the actual GitHub settings or published assets.
