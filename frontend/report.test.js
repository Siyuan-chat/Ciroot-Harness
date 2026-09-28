import test from 'node:test';
import assert from 'node:assert/strict';
import {renderReport,renderReportSelection} from './pages/report.js';
import {loadEvidenceContext,renderEvidenceInspector,humanLocator} from './components/evidence-inspector.js';
import {renderDocumentInspector} from './components/document-inspector.js';
import {renderEvidenceTrace} from './components/evidence-trace.js';
import {t} from './i18n.js';
import {readFile} from 'node:fs/promises';

const locale='en';
const evidence={evidence_id:'ev-1',document_id:'doc-1',version_id:'v2',text:'Exact source quotation',locator:{kind:'pdf_page',value:7}};
const claims=[{claim_id:'claim-1',claim:'Bound claim',verification:'verified',evidence_refs:['ev-1']}];
const report={research_question:'Question from the saved run',synthetic:true,sections:[{title:'Findings',deliverable_type:'technical_report',body:'Report prose stays authored as supplied.',claim_ids:['claim-1','not-in-report']}],claims,evidence:[evidence],bibliography:[{id:'doc-1',title:'Source title'}]};

test('report binds section claim_ids to claims and renders only their explicit evidence_refs as evidence chips',()=>{
  const html=renderReport({run:{run_id:'run-real',status:'partial',synthetic:true},result:{outcome:'partial'},reportData:report,t,locale});
  assert.match(html,/data-report-content="true">Report prose stays authored as supplied\./);
  assert.match(html,/Bound claim/);
  assert.match(html,/<h4 title="claim-1">Claim 1<\/h4>/);
  assert.match(html,/<dt>claim ids<\/dt><dd><code>claim-1<\/code>/);
  assert.match(html,/data-evidence-id="ev-1" data-claim-id="claim-1"/);
  assert.match(html,/Referenced claim data is unavailable: not-in-report/);
  assert.match(html,/partial/);
  assert.match(html,/run-real/);
  assert.doesNotMatch(html,/data-evidence-id="not-in-report"/);
  assert.doesNotMatch(html,/data-page="reader"|href="[^"]*reader/i);
});

test('missing reference remains an explicit unavailable item and no inline citation is inferred',()=>{
  const html=renderEvidenceTrace({claim:{claim_id:'c',claim:'A [1] claim',evidence_refs:['missing-id']},evidence:[],bibliography:[],t,locale});
  assert.match(html,/Referenced evidence item unavailable/);
  assert.doesNotMatch(html,/data-evidence-id=/);
  const noRefs=renderEvidenceTrace({claim:{claim:'No refs'},evidence:[evidence],bibliography:[],t,locale});
  assert.match(noRefs,/No evidence is linked to this claim/);
});

test('shared evidence loader keeps selected scope, run identity and service source scope while resolving document/version',async()=>{
  const calls=[];
  const api={
    evidence:async(id,runId,scope)=>{calls.push(['evidence',id,runId,scope]);return {evidence:{items:[{...evidence},{evidence_id:'other'}]},source_scope:{library_id:'frozen-library',collection_id:'source'},locator_insufficient:true}},
    libraryDocument:async(id,scope)=>{calls.push(['libraryDocument',id,scope]);return {document:{document_id:id,title:'Source title',versions:[{version_id:'v2',file_url:'/api/v1/library/documents/doc-1/versions/v2/file'}]}}},
    runDocument:async(...args)=>{calls.push(['runDocument',...args]);throw new Error('library source preferred')}
  };
  const scope={workspaceId:'workspace-1',libraryId:'library-1',collectionId:'collection-1'};
  const context=await loadEvidenceContext(api,'ev-1','run-real',scope);
  assert.equal(context.evidence.evidence_id,'ev-1');
  assert.equal(context.document.document_id,'doc-1');
  assert.equal(context.locatorInsufficient,true);
  assert.deepEqual(calls[0],['evidence','ev-1','run-real',scope]);
  assert.deepEqual(calls[1],['libraryDocument','doc-1',{...scope,libraryId:'frozen-library',collectionId:'all'}]);
  const html=renderEvidenceInspector({context,claim:claims[0],claims,t,locale});
  assert.match(html,/Exact source quotation/);
  assert.match(html,/Page 7/);
  assert.match(html,/href="\/api\/v1\/library\/documents\/doc-1\/versions\/v2\/file"/);
  assert.match(html,/locatorInsufficient|insufficient source location/);
  assert.match(html,/Advanced identifiers/);
});

test('inspectors expose only service URLs and show missing originals explicitly',()=>{
  const noUrl=renderEvidenceInspector({context:{evidence,document:{title:'Source',versions:[{version_id:'v2',file_url:'https://example.invalid/private'}]}},claims:[],t,locale});
  assert.match(noUrl,/No original file link is available/);
  assert.doesNotMatch(noUrl,/example\.invalid/);
  const doc=renderDocumentInspector({document:{document_id:'doc-1',title:'Source title',index_status:'ready',versions:[{version_id:'v2',file_url:'/api/v1/library/documents/doc-1/versions/v2/file'}]},t,locale});
  assert.match(doc,/Open version v2/);
  assert.match(doc,/href="\/api\/v1\//);
  const noVersion=renderDocumentInspector({document:{document_id:'empty',title:'Empty',versions:[]},t,locale});
  assert.match(noVersion,/No original file link is available/);
});

test('human-readable locator is localized and unknown locator remains explicit',()=>{
  assert.equal(humanLocator({kind:'paragraph',value:3},t,'zh'),'段落 3');
  assert.equal(humanLocator({kind:'pdf_page',value:7},t,'ja'),'7 ページ');
  assert.match(humanLocator(null,t,'en'),/readable locator/);
});

test('report selection only offers real runs returned by the API',()=>{
  const html=renderReportSelection({runs:[{run_id:'run-1',status:'partial',research_question:'Saved question'}],t,locale});
  assert.match(html,/Saved question/);
  assert.match(html,/data-open-report-run="run-1"/);
  assert.doesNotMatch(html,/sample|fake/i);
  for(const language of ['zh','en','ja'])assert.match(renderReportSelection({runs:[],t,locale:language}),new RegExp(language==='zh'?'选择调查报告':language==='en'?'Select an investigation report':'調査レポートを選択'));
});

test('claim labels are readable in all supported locales while section identity stays bound',()=>{
  const labels={zh:'主张 1',en:'Claim 1',ja:'主張 1'};
  for(const [language,label] of Object.entries(labels)){
    const html=renderReport({run:{run_id:'run-real'},reportData:report,t,locale:language});
    assert.ok(html.includes(label));
    assert.match(html,/data-evidence-id="ev-1" data-claim-id="claim-1"/);
  }
});

test('report sections use a continuous reading surface rather than bordered cards',async()=>{
  const css=await readFile(new URL('./style.css',import.meta.url),'utf8');
  assert.match(css,/\.report-section\{[^}]*background:transparent;[^}]*border:0;[^}]*border-bottom:1px solid/);
  assert.match(css,/\.report-claim\{[^}]*border:0;[^}]*background:transparent/);
});

test('app opens evidence in one contextual inspector, keeps the current report route and returns focus on close',async()=>{
  const app=await readFile(new URL('./app.js',import.meta.url),'utf8');
  const open=app.match(/async function openEvidence\([\s\S]*?\nasync function verifyLocator/ )?.[0]||'';
  assert.match(open,/loadEvidenceContext\(api,id,runId,scope\)/);
  assert.match(open,/state\.inspector=\{open:true,type:'evidence'/);
  const inspectorPath=open.slice(open.indexOf("state.inspector={open:true"));
  assert.doesNotMatch(inspectorPath,/state\.page=/);
  assert.match(app,/app\.querySelector\('#reader-open'\).*\{reader:true\}/);
  assert.match(app,/function closeInspector\(\)\{[\s\S]*?render\(\)/);
  assert.match(app,/event\.key==='Escape'&&state\.inspector\.open/);
  assert.match(app,/item\.dataset\.evidenceId===focus\.id/);
});
