Input: completed task outputs named by `input_refs` and their evidence facts.
Output the declared schema by joining only those results, resolving conflicts
with qualifiers and gaps. Each claim binds to one document/version and quotes
a continuous excerpt sufficient for that claim. Keep cross-document comparison
in separate claims; the later prose must cite both claims. Do not splice
conditions from different materials or tests. Review retellings are not primary
experimental evidence; do not fill missing values or produce unsupported
universal claims.
When a cited evidence item includes `parse_revision_id`, copy that exact value
to the claim's `parse_revision_id`. Never substitute the document's current
parse revision for the revision frozen in the evidence payload. Legacy evidence
without a parse revision may omit this field.
