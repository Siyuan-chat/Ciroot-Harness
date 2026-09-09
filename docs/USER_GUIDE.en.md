# English user guide — target interface, not implemented yet

This guide specifies the user journey Terra must implement. The design package does not currently provide a working rh command. Terra will add installation steps after testing them. v1 runs locally and updates only when the user asks; polymer-design case evaluation follows implementation.

## 1. Workspace and APIs

Research intent belongs in research.json. Provider/model selection belongs in runtime.json. Credentials are supplied through environment variables referenced by name.

The [runtime template](../examples/runtime.example.json) has null model selections. It cannot start an investigation. Terra must supply a verified multilingual local embedding default after integration testing; users select a generation model they can access. Schema validity does not prove model/API availability.

OpenAlex and EPO have separate credentials and content coverage. A discovered record does not guarantee full-text access. Supported providers need configuration only; a new API service needs an adapter.

Original files, databases, indexes, dialogue sessions and reports live under workspace/ and stay out of Git by default. Embeddings are generated locally. Relevant source excerpts may be sent to the configured model for analysis. External speech-to-text output can be pasted into chat; v1 does not include microphone recording.

## 2. Check configuration and describe the task

The commands below are required future interfaces:

```text
rh doctor --runtime runtime.json --workspace workspace
rh chat --runtime runtime.json --workspace workspace --lang en
```

doctor performs local checks by default. Missing credentials, dependencies or model selections receive actionable messages. Optional explicit online checks must be distinguished from local validation.

Describe the task, for example: “Investigate the design of the selected polymer using my local papers and patents. Compare design approaches and the available performance evidence.”

The intake agent asks one consequential question at a time, reuses known answers and produces a readable summary plus a versioned JSON specification. It does not invent scientific thresholds. Revising requirements saves a new version; an explicit “start the investigation” or “update the investigation” triggers execution.

The [polymer-design draft](../examples/polymer-design.draft.json) records the agreed topic only. It is not a complete case and cannot execute.

## 3. Import reference material

```text
rh import ./my-paper.pdf --workspace workspace --collection baseline --kind paper
rh import ./my-patent.xml --workspace workspace --collection baseline --kind patent
```

Originals retain version and location information. Newly retrieved material enters the discovery library. Promotion into the reference library is explicit. Each investigation freezes its reference versions before comparison begins.

## 4. Update, resume and inspect reports

Use natural-language requests in chat to update, inspect progress or revise the focus. Explicit commands provide the same services:

```text
rh validate --spec research.json
rh run --spec research.json --runtime runtime.json --workspace workspace
rh status --workspace workspace
rh resume RUN_ID --runtime runtime.json --workspace workspace
rh report RUN_ID --workspace workspace --languages zh,en,ja
```

Candidate counts, query rounds, model calls, download sizes and active execution time are bounded. Reaching a limit saves available results and produces a partial report. Estimated model cost is not the provider invoice; missing pricing is reported as unknown, not zero.

Outputs include HTML/Markdown reports, canonical JSON facts and a CSV review list. The three languages share facts and record IDs. Reports distinguish completed searches with no additions from unavailable sources. Technical-map entries and noteworthy developments link to original evidence.

## 5. Human review

```text
rh review list --workspace workspace --lang en
rh review decide ISSUE_ID --decision watch --note "Monitor for further evidence" --workspace workspace
```

Decisions are include, exclude, watch or request_more_evidence. A human watch decision is resolved monitoring, distinct from an unanswered evidence issue. Follow-up evidence requests are handled on the next user-triggered run.

The same issue is not repeatedly added. Material new evidence can reopen it, preserving prior decisions. All language views share state. An individual decision does not change global rules; explicitly request a rule change when that is intended.

## 6. Reading results

- An unreported value is neither zero nor a failed threshold.
- Measurements made under different conditions are not directly comparable.
- Abstracts, claims, descriptions, examples and paper results have distinct evidence roles.
- A valid citation location does not by itself prove a conclusion; important judgments remain reviewable.
- Historical reports preserve their original snapshot. A newer review view does not erase history.
- This is currently a design package. Later versions must distinguish local tests, live API verification and scientific case acceptance.
