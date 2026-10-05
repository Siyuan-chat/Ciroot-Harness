# Synthetic offline adapter example

This fixture is entirely synthetic and is not scientific evidence or a real patent record. Its publication, version, revision, evidence, locator and text identifiers are placeholders created only to demonstrate the local JSON contract. Do not cite it or use it to infer patent structure or scientific conclusions.

Run the CLI with the absolute path to this file:

```powershell
rh patent-analyze --input "C:\path\to\AEM\examples\patent_analysis\frozen-input.synthetic.json"
```

The command reads this JSON, computes its SHA-256, and prints a structural summary. It does not modify the workspace database, download sources, or accept claims. The result always reports claim acceptance as `not_assessed`.
