Input: the candidate claims, citations and artifacts in `input_refs`. Output
the declared verification schema with failures, coverage and human-review
items. Check document/version, locator, units, conditions, and whether each
exact quote supports the complete claim. Report a gap when mapping is unclear,
conditions were combined, or a factual error is found; use `partial` rather
than guessing or accepting an unsupported result.
