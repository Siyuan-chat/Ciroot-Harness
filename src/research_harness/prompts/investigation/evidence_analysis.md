Input: the explicit `evidence`, `baseline_evidence`, and
`discovery_evidence` payload fields. `input_refs` records stage/task lineage;
it is not itself the complete evidence list. Analyze the provided baseline and
attached RAG evidence before submission. Extract each material/test condition
separately (concentration, temperature, time, method, and metric when
reported); preserve missing, uncertain, and conflicting conditions. Output the
declared schema with evidence_id, document/version and physical or source
locator. Quotes must be continuous source substrings; do not trust a
model-provided verified flag.
