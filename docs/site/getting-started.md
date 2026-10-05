---
title: Getting started with CirootHarness
description: Start with the CirootHarness Windows preview or deterministic offline Golden Demo.
---

# Getting started

There are two public entry points: the Windows desktop preview and the deterministic offline Golden Demo.

## Windows desktop preview

Download the current portable ZIP from [GitHub Releases](https://github.com/Siyuan-chat/Ciroot-Harness/releases), extract the complete `ResearchHarnessGUI` folder, and launch:

```text
ResearchHarnessGUI.exe
```

The product window is branded **CirootHarness**. The executable name is retained for compatibility.

The preview does not bundle private documents, model caches, or API credentials.

## Deterministic offline Golden Demo

Python 3.11+ is required. Installation may require network access, but the demo itself is designed to execute offline.

### Windows

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install ".[investigation]"
.venv\Scripts\rh investigate --workspace .local/golden-demo golden-demo
```

### macOS / Linux

```bash
python -m venv .venv
.venv/bin/python -m pip install ".[investigation]"
.venv/bin/rh investigate --workspace .local/golden-demo golden-demo
```

The Golden Demo intentionally includes one malformed synthetic XML document. Its expected result is therefore `partial`, not `completed`. That behavior demonstrates the project's rule that incomplete coverage remains visible instead of being rewritten into certainty.

For persisted outputs and reopening instructions, read the [Golden Demo guide](https://github.com/Siyuan-chat/Ciroot-Harness/blob/master/docs/GOLDEN_DEMO.md).

## Before using live integrations

Read [Current status](current-status.md). Component availability, API wiring, and semantic/scientific acceptance are tracked separately.
