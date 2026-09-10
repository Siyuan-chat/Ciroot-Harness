"""Independent real-PDF table checks against the visually verified Khalid page 5."""
import argparse
import json
import sqlite3
import tempfile
from pathlib import Path

from research_harness.rag import RagLibrary, RagError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    checks = {}
    # A read-only SQLite backup permits checking context while the source index is busy.
    # This probe never opens the source Qdrant collection or modifies source evidence.
    with tempfile.TemporaryDirectory(prefix='rag-context-') as directory:
        source = sqlite3.connect((Path(args.workspace) / 'rag.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
        copied = sqlite3.connect(Path(directory) / 'rag.sqlite')
        source.backup(copied)
        source.close()
        copied.close()
        with RagLibrary(directory) as lib:
            rows = lib._db.execute("SELECT e.* FROM rag_evidence e JOIN rag_documents d ON d.document_id=e.document_id WHERE d.doi=? AND e.role='table'", ('10.3390/membranes12100989',)).fetchall()
            table = next(row for row in rows if 'Tested membranes and their specifications' in row['text'])
            evidence_id = table['evidence_id']
            context = lib.get_evidence_context(evidence_id, before=0, after=1)
            target = context['items'][0]
            checks['physical_page_5'] = target['locator']['page'] == 5
            checks['one_meaningful_following_block'] = len(context['items']) == 2
            checks['footnote_preserved'] = 'na: not available' in context['items'][-1]['text'] and 'presumably hydroxide' in context['items'][-1]['text']
            checks['same_document_version'] = all(item['document_id'] == target['document_id'] and item['version_id'] == target['version_id'] for item in context['items'])
            checks['zero_context_only_target'] = [item['evidence_id'] for item in lib.get_evidence_context(evidence_id, before=0, after=0)['items']] == [evidence_id]
            lines = [[cell.strip() for cell in line.strip().strip('|').split('|')] for line in target['text'].splitlines() if line.startswith('|')]
            headers = next(line for line in lines if 'PI-15' in line)
            iec = next(line for line in lines if line[0] == 'IEC [mmol/g]')
            checks['pi15_missing_not_zero'] = iec[headers.index('PI-15')] == 'na'
            checks['pi20_value_and_footnote'] = iec[headers.index('PI-20')] == '2.35 a'
            checks['table_eight_columns'] = len(headers) == len(iec) == 8
            for value in [-1, 4]:
                try:
                    lib.get_evidence_context(evidence_id, after=value)
                    checks[f'invalid_window_{value}'] = False
                except RagError as exc:
                    checks[f'invalid_window_{value}'] = exc.code == 'RH_RAG_INVALID_INPUT'
    report = {'checks': checks, 'context': context, 'basis': 'Visually checked original Khalid 2022 PDF, physical page 5; no model answer used as reference.'}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': checks}, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
