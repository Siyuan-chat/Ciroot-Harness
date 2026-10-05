# Offline integration evaluation fixtures

This directory contains synthetic, non-scientific inputs for checking the evaluator contract. The one evidence passage and the three frozen result files are fabricated fixtures; they are not copied from the private S2 AEM case and do not make claims about research quality.

From the repository root, run:

```powershell
.local/d19-runtime/venv/Scripts/python.exe scripts/evaluate_integration.py `
  --case examples/integration_evaluation/case.json `
  --results-dir examples/integration_evaluation `
  --annotations examples/integration_evaluation/annotations-template.json
```

The evaluator reports offline metrics, leaves unannotated claims as `not_assessed`, and keeps the RAG/PaperQA/STORM comparison at `pending_activation`. It never executes a model, queries a source, or writes to an investigation database. To assess a real comparison, supply three frozen result records with matching corpus digest, question digest, model and numerical budget, plus evidence-backed accepted physical model-call IDs from the core ledger. This readiness check does not judge the research claims or infer an improvement.

Copy the annotation template for a review and fill each claim's label (`supported`, `partial`, `unsupported`, or `contradicted`), annotator, source locator, comparison conditions, reason, and measured review seconds. Leave a label empty until it has actually been judged.
