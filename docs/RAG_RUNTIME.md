# Local RAG runtime

The D18 runtime is local: Docling 2.126.0, FastEmbed 0.8.0, Qdrant client 1.19.0, and LlamaIndex core 0.14.24. The default embedding is `intfloat/multilingual-e5-small`, registered through FastEmbed 0.8 with mean pooling, normalization, 384 dimensions, and `query:`/`passage:` prefixes. The tested artifact is Hugging Face revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`; its `onnx/model.onnx` SHA-256 is `ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665` and its model card declares MIT: <https://huggingface.co/intfloat/multilingual-e5-small>. A same-named future artifact is not covered by this verification.

The `full`, `rag`, and `rag-mcp` extras pin NLTK 3.9.3. LlamaIndex core 0.14.24 declares `nltk>=3.9.3`; the former 3.9.2 pin made a fresh RAG install fail `pip check`. NLTK is not part of the stored embedding fingerprint, so this compatibility correction does not change an existing index identity.

The tested local execution settings are `threads=2` and `batch_size=16`. They affect batching and CPU parallelism only; they do not change the model, dimension, or embedding preprocessing.

The tested default E5 tokenizer accepts 512 tokens. The explicit legacy `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` model instead reports `max_length=128` and `model_max_length=512`; FastEmbed uses their minimum, so its vectors are effectively limited to 128 tokens. Body chunks are 200 LlamaIndex tokens and tables remain whole evidence blocks, so long inputs can still be truncated for vector retrieval while returned evidence and context remain complete. This retrieval-quality limitation will be evaluated on the frozen set before changing chunking or table indexing.

`full_text` records that each converted page has text coverage; it does not certify that every figure caption or figure-derived reading is scientifically accurate. The Clemens import showed repeated and garbled figure-caption extraction, an extraction limitation rather than a statement about the source paper. Check the rendered original PDF before using quantitative conclusions from figures.

Set cache locations before the first import so weights are reusable and remain outside Git:

```powershell
$env:RAG_MODEL_CACHE = "$PWD\.local\rag-runtime\models"
$env:HF_HOME = "$PWD\.local\rag-runtime\huggingface"
python -m pip install ".[rag-mcp]"
```

The runtime does not read Codex credentials and does not call a generation model. Acceptance status is maintained in the [independent RAG acceptance record](RAG_ACCEPTANCE.md).

The default E5 model and the explicit legacy MiniLM model have been tested in this stage. A different `embedding_model` is rejected against an existing index when its fingerprint differs; arbitrary embedding models have not been validated, and dynamic dimension and preprocessing discovery is not implemented.

## Local regression record

On the bundled Python runtime, `python -m pytest -q tests/test_rag_cli.py tests/test_rag_prepare.py tests/test_rag_mcp.py` passed 7 tests on 2026-09-10. Pytest reported one non-product warning because the worktree denied creation of `.pytest_cache`. BM25Okapi has an expected two-document IDF edge case: a token present in one of two documents can receive zero IDF under the library's epsilon rule. A three-document synthetic corpus distinguished a rare token, and an 8,820-document synthetic corpus built and queried in 0.039 seconds; an all-empty token corpus uses the vector-only branch.
