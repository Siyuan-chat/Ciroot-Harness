"""D2 report facts and minimal multilingual presentation; synthetic inputs."""
import argparse
import html
import json
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--source', required=True)
p.add_argument('--output', required=True)
a = p.parse_args()
source = Path(a.source).resolve()
output = Path(a.output).resolve()
output.parent.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(source / 'src'))
from research_harness.service import Harness

class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.tags = []; self.parts = []
    def handle_starttag(self, tag, attrs): self.tags.append(tag)
    def handle_data(self, data): self.parts.append(data)

results = {}
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); h = Harness(root / 'workspace')
    baseline = root / 'baseline.txt'; baseline.write_text('Synthetic baseline evidence.', encoding='utf-8')
    h.import_document(baseline, 'baseline', 'paper')
    spec = json.loads((source / 'examples/polymer-design.draft.json').read_text(encoding='utf-8'))
    spec.update(status='ready', unresolved_questions=[])
    spec['execution']['budget']['max_candidates'] = 2
    sp = root / 'spec.json'; sp.write_text(json.dumps(spec), encoding='utf-8')
    fp = root / 'fixture.json'; fp.write_text(json.dumps({'candidates': [
        {'id': 'synthetic-<img src=x onerror=alert(1)>|id', 'quote': 'Synthetic <script>alert(1)</script> original.', 'locator': 'line:1'},
        {'id': 'synthetic-missing', 'quote': 'Synthetic evidence gap.', 'locator': 'line:1', 'missing': True},
        {'id': 'synthetic-over-budget', 'quote': 'Synthetic omitted candidate.', 'locator': 'line:1'}]}), encoding='utf-8')
    rationale = 'SYNTHETIC_RATIONALE_MARKER'
    def model(spec, candidate, ce, re):
        return {'disposition': 'include', 'comparison_result': 'not_comparable', 'rationale': rationale,
                'candidate_citations': [] if candidate.get('missing') else [{'evidence_id': ce[0]['id'], 'quote': ce[0]['quote']}],
                'reference_citations': [{'evidence_id': re[0]['id'], 'quote': re[0]['quote']}]}
    run = h.run_fixture(sp, fp, model_adapter=model)
    report_dir = Path(run['artifacts']['report']); data = json.loads((report_dir / 'report.json').read_text(encoding='utf-8'))
    ids = [c['id'] for c in data['candidates']] + [c['document_id'] for c in data['candidates']]
    evidence = [e for c in data['candidates'] for e in c['evidence']] + data['reference_evidence']
    for lang in ('zh', 'en', 'ja'):
        md = (report_dir / f'report.{lang}.md').read_text(encoding='utf-8')
        page = Page(); page.feed((report_dir / f'report.{lang}.html').read_text(encoding='utf-8'))
        text = html.unescape(''.join(page.parts)); decoded_md = html.unescape(md)
        both = (text, decoded_md)
        results[lang] = {
            'candidate_document_ids': all(all(i in t for i in ids) for t in both),
            'rationale_visible': all(rationale in t for t in both),
            'evidence_and_locator_visible': all(all(e['id'] in t and e['locator'] in t for e in evidence) for t in both),
            'review_issue_visible': all(data['issues'][0]['id'] in t for t in both),
            'run_id_visible': all(run['run_id'] in t for t in both),
            'partial_visible': all(any(s in t for s in ('partial', '部分完成', '一部完了')) for t in both),
            'budget_reason_visible': all('max_candidates' in t for t in both),
            'synthetic_notice_visible': all(any(s in t for s in ('合成夹具', 'Synthetic fixture', '合成フィクスチャ')) for t in both),
            'verification_visible': all(any(s in t for s in ('invalid', '无效', '無効')) for t in both),
            'localized_body_headings': lang == 'en' or not any(s in md for s in ('Evidence (original)', '| Disposition |', '| Comparison |', '| Verification |')),
            'localized_markdown_run_state': lang == 'en' or {'zh': '部分完成', 'ja': '一部完了'}[lang] in decoded_md,
            'localized_html_review_headers': lang == 'en' or not any(s in text for s in ('StatusMachineDecisionNote', 'StatusMachine')),
            'rationale_original_label': all({'zh': '模型原文', 'en': 'model original', 'ja': 'モデル原文'}[lang] in t for t in both),
            'html_no_active_external_tags': not any(tag in page.tags for tag in ('img', 'script', 'iframe')),
            'markdown_no_active_external_tags': not re.search(r'<\s*(img|script|iframe)\b', md, re.I),
        }
    shutil.copytree(report_dir, output.parent / 'report-view', dirs_exist_ok=True)
    h.store.close()
output.write_text(json.dumps(results, indent=2), encoding='utf-8')
print(json.dumps(results, indent=2))
raise SystemExit(0 if all(all(r.values()) for r in results.values()) else 1)
