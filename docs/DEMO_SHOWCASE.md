# CirootHarness demo showcase guide

This guide defines how to turn the existing engineering assets into a public demo without overstating capability.

The public story should be understandable by a hiring manager, researcher, engineer, or open-source user who has never read the D2/D18/D19 documents.

## The four things the demo must prove

A good CirootHarness demo should visibly prove that:

1. a natural-language question becomes a concrete, frozen research specification;
2. source attempts and coverage are recorded instead of hidden;
3. report claims can be followed back to evidence and a source locator;
4. unresolved ambiguity remains visible as review work instead of being rewritten into certainty.

Everything else is secondary.

## Canonical 60–90 second story

Use the deterministic synthetic/offline path unless a separate live run has its own acceptance record.

### 0–10 s — Start from a question

Show a clean CirootHarness workspace and enter one bounded research question.

On-screen message:

> Define the research question before the agent searches.

### 10–25 s — Show the frozen plan

Show the generated/specification view:

- research question;
- scope;
- criteria;
- reference set;
- budget / candidate limits;
- report targets.

Highlight that execution does not begin until the user explicitly starts it.

On-screen message:

> Requirements are versioned and frozen before execution.

### 25–45 s — Run and expose source state

Show the run progressing through planning/retrieval/evidence steps.

The UI should expose:

- source/query attempts;
- `complete` / `partial` / `failed` state;
- budget use;
- synthetic/offline badge when applicable.

On-screen message:

> Retrieval failures stay visible. `partial` is not `completed`.

### 45–65 s — Open one claim back to evidence

From the report, click one evidence reference.

Show:

- evidence ID;
- document/version identity;
- quote/excerpt;
- page/paragraph/XML locator;
- source preview when available.

On-screen message:

> Every important claim should be inspectable at the source.

### 65–80 s — Show human review

Open one unresolved review issue and show decision history or the available review action.

On-screen message:

> Uncertainty is routed to review instead of hidden in prose.

### 80–90 s — Finish on the report

Show the report/export view and the final run status.

End card:

> CirootHarness — auditable AI research for patents and scientific literature.

## Required screenshot set

Capture these images after the UI is stable:

1. `01-workspace-overview.png`
   - workspace/library/run visible;
   - no private documents, API keys, local usernames or private paths.

2. `02-research-spec.png`
   - bounded research question and frozen constraints.

3. `03-run-source-status.png`
   - source attempts and explicit coverage state.

4. `04-evidence-trace.png`
   - claim/evidence ID plus locator or source preview.

5. `05-human-review.png`
   - unresolved issue and decision UI.

6. `06-final-report.png`
   - technical report / literature review and evidence links.

Store final public assets in `assets/demo/`.

## README hero asset

Once the screenshots exist, create one hero image rather than placing six full-size screenshots above the fold.

Recommended composition:

- left: workspace / question;
- center: research progress or evidence;
- right: final report;
- small footer labels: `Versioned spec · Evidence trace · Explicit coverage · Human review`.

Do not create a fake interface mockup that looks more complete than the shipped product. The hero should be built from real screenshots of a reproducible demo run.

## Capture rules

- Use only synthetic or explicitly redistributable source material.
- Hide API keys, local file paths, account names and machine-specific identifiers.
- Keep the same demo workspace across screenshots.
- Use the same question, evidence IDs and final report across the entire story.
- Capture at a consistent desktop size.
- Prefer PNG for screenshots and WebM/MP4 or optimized animated WebP for motion.
- Keep README animation short enough that GitHub rendering remains usable.
- A video can be longer, but the README should communicate the product without requiring playback.

## Golden demo acceptance criteria

The public demo is ready only when a clean user can:

1. start from an empty or clearly marked demo workspace;
2. load the approved synthetic scenario without API credentials;
3. run it without network access;
4. receive the same bounded set of outputs;
5. open at least one report claim back to evidence;
6. see at least one review issue;
7. see a truthful final status;
8. reopen the result after restarting the application or service.

If any of these are not yet possible, the README should state the limitation rather than simulate it.

## Public copy rules

Prefer concrete claims:

- “records source attempts”
- “links claims to evidence IDs”
- “supports an offline deterministic demo”
- “produces a partial outcome when coverage is incomplete”

Avoid broad claims until benchmarked:

- “finds all relevant patents”
- “eliminates hallucinations”
- “fully automates patent research”
- “replaces patent attorneys”
- “production-ready enterprise monitoring”

## Social preview

After a real hero screenshot exists, create a 1280×640 repository social preview with:

- CirootHarness logo/name;
- “Auditable AI research for patents & scientific literature”;
- one real product screenshot crop;
- `Evidence-linked · Local-first · Reviewable`.

Repository social-preview configuration is a GitHub setting and is intentionally not automated by this file. Canonical repository description, topics, preview copy and SEO/GEO query baselines are tracked in [SEO_GEO_BASELINE.md](SEO_GEO_BASELINE.md).
