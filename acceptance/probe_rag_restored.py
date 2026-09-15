"""Read-only retrieval acceptance against an existing, frozen local RAG index."""
from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import sqlite3
import sys
import time


def snapshot(workspace):
    with sqlite3.connect((workspace / 'rag.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        return {**{name: db.execute('SELECT COUNT(*) FROM rag_' + name).fetchone()[0]
                   for name in ('documents', 'versions', 'evidence')},
                'config': dict(db.execute('SELECT key,value FROM rag_config'))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    before = json.loads(args.before.read_text(encoding='utf-8'))
    assert snapshot(workspace) == before

    def audit(event, values):
        if event == 'socket.connect':
            raise RuntimeError('Restoration acceptance must use cached models without network')
    sys.addaudithook(audit)
    from research_harness.rag import RagLibrary
    times = {}
    with RagLibrary(workspace) as library:
        start = time.perf_counter()
        status = library.get_library_status()
        times['status'] = round(time.perf_counter() - start, 3)
        assert status['index_status'] == 'ready', status
        assert status['indexed_document_count'] == before['documents']
        collection = before['config']['active_collection']
        points = library._qdrant.count(collection, exact=True).count
        assert points == before['evidence']
        start = time.perf_counter()
        search = library.search_evidence('piperidinium anion exchange membrane', top_k=3)
        times['search'] = round(time.perf_counter() - start, 3)
        assert len(search['items']) == 3
        assert search['diagnostics']['vector_hits'] > 0 and search['diagnostics']['lexical_hits'] > 0
        first = search['items'][0]
        context = library.get_evidence_context(first['evidence_id'])
        assert any(x['evidence_id'] == first['evidence_id'] and x['text'] == first['text'] for x in context['items'])
        assert all(x['version_id'] == first['version_id'] for x in context['items'])
    after = snapshot(workspace)
    assert after == before, 'Existing corpus or active index configuration changed'
    report = {'status': 'passed', 'seconds': times, 'points': points, 'library_status': status,
              'search': search, 'context': context, 'corpus_snapshot': after,
              'versions': {name: version(name) for name in ('fastembed', 'docling', 'qdrant-client', 'llama-index-core', 'mcp')},
              'scope': 'existing index retrieval and exact context; no import, rebuild or document embedding; external network forbidden'}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('status', 'seconds', 'points', 'versions', 'scope')}))


if __name__ == '__main__':
    main()
