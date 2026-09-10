# Local RAG runtime

The D18 runtime is local: Docling 2.126.0, FastEmbed 0.8.0, Qdrant client 1.19.0, and LlamaIndex core 0.14.24. The tested embedding is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, using FastEmbed 0.8 mean pooling and 384 dimensions. Its Hugging Face model card declares Apache-2.0: <https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2>.

The tested local execution settings are `threads=2` and `batch_size=16`. They affect batching and CPU parallelism only; they do not change the model, dimension, or embedding preprocessing.

The cached tokenizer configuration reports `max_length=128` and `model_max_length=512`; FastEmbed uses their minimum, so embeddings are effectively limited to 128 tokens. Body chunks are 200 LlamaIndex tokens and tables remain whole evidence blocks, so long inputs can be truncated for vector retrieval while returned evidence and context remain complete. This recorded retrieval-quality limitation will be evaluated on the frozen set before changing chunking or table indexing.

Set cache locations before the first import so weights are reusable and remain outside Git:

```powershell
$env:RAG_MODEL_CACHE = "$PWD\.local\rag-runtime\models"
$env:HF_HOME = "$PWD\.local\rag-runtime\huggingface"
python -m pip install ".[rag-mcp]"
```

The runtime does not read Codex credentials and does not call a generation model. Real FastEmbed/Qdrant TXT import and search, Docling single-page PDF conversion, and MCP STDIO protocol have been checked locally. Full 23-document import, multilingual retrieval scoring, and host-session acceptance remain pending.

Only the default embedding is tested. A different `embedding_model` is rejected against an existing index when its fingerprint differs; dynamic dimension and preprocessing discovery for arbitrary models is not implemented or validated in this stage.
