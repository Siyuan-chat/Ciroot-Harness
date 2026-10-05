import test from 'node:test';
import assert from 'node:assert/strict';
import {renderInvestigationWorkspace,renderInvestigationList,projectInvestigationProgress,isCurrentInvestigationResponse,fetchInvestigationList} from './pages/investigation.js';
import {t} from './i18n.js';

const render=(run={},result=null,reportData=null,locale='en')=>renderInvestigationWorkspace({run,result,reportData,tasks:[],events:[],t,locale});

test('investigation response accepts the selected run and rejects stale or mismatched responses',()=>{
  const scope={workspaceId:'w1',libraryId:'l1',collectionId:'c1'};
  const request={scope,currentScope:scope,runId:'run-1',selectedRunId:'run-1',responseRunId:'run-1',generation:4,currentGeneration:4};
  assert.equal(isCurrentInvestigationResponse(request),true);
  assert.equal(isCurrentInvestigationResponse({...request,currentGeneration:5}),false);
  assert.equal(isCurrentInvestigationResponse({...request,selectedRunId:'run-2'}),false);
  assert.equal(isCurrentInvestigationResponse({...request,responseRunId:'run-2'}),false);
  assert.equal(isCurrentInvestigationResponse({...request,currentScope:{...scope,libraryId:'l2'}}),false);
});

test('investigation navigation loads and renders real scoped run items',async()=>{
  const scope={workspaceId:'w1',libraryId:'l1',collectionId:'c1'};
  const api={runs:async(cursor,requestScope)=>{assert.equal(cursor,null);assert.equal(requestScope,scope);return {items:[{run_id:'run-1',project_id:'project-1',status:'waiting',stage:'planning'}],next_cursor:'next'}}};
  const page=await fetchInvestigationList(api,scope);
  assert.equal(page.next,'next');
  assert.match(renderInvestigationList({...page,t,locale:'en'}),/project-1/);
  assert.match(renderInvestigationList({...page,t,locale:'en'}),/data-open-investigation="run-1"/);
});

test('partial outcome stays partial even when the stage reached completed',()=>{
  const html=render({run_id:'r1',stage:'completed',status:'completed'},{outcome:'partial'},{});
  assert.match(html,/status-partial/);
  assert.doesNotMatch(html,/status-completed/);
});

test('unknown metrics stay unknown and progress never invents a denominator',()=>{
  const html=render({run_id:'r1',stage:'source',coverage:{}},null,null);
  assert.match(html,/Unknown/);
  assert.doesNotMatch(html,/\b\d+\s*\/\s*\d+\b/);
  const steps=projectInvestigationProgress({run:{stage:'source'},coverage:{}});
  assert.ok(steps.every(step=>step.detail===null));
});

test('Patent Compare requires explicit patent bibliography metadata',()=>{
  assert.doesNotMatch(render({run_id:'r1'},null,{bibliography:[{id:'b1',title:'Patent application 123'}]}),/Patent Compare/);
  assert.match(render({run_id:'r1'},null,{bibliography:[{id:'b1',type:'patent',title:'Document'}]}),/Patent Compare/);
});

test('issue cards expose evidence context without inventing action controls',()=>{
  const html=render({run_id:'r1'},{outcome:'partial',issues:[{code:'RH_NORMALIZE_XML',status:'open',reason:'Parser warning',impact:'Evidence may be incomplete'}]},{});
  assert.match(html,/Parser warning/);
  assert.match(html,/Evidence may be incomplete/);
  assert.doesNotMatch(html,/data-investigation-action="review/);
});

test('Golden Demo shaped stage trace renders every progress step safely',()=>{
  const run={run_id:'inv-demo',stage:'completed',status:'partial',synthetic:true,coverage:{candidate_count:2,complete:false,queries:[]},stage_trace:[
    {node:'planning_gate',event:'planned'},
    {node:'source_task',event:'screened'},
    {node:'acquire_normalize',event:'normalized'},
    {node:'analysis_task',event:'analyzed'},
    {node:'verification_gate',event:'source_partial'},
  ]};
  const result={outcome:'partial',evidence:[{evidence_id:'ev-1',document_id:'doc-1'},{evidence_id:'ev-2',document_id:'doc-1'}],issues:[]};
  const reportData={claims:[{claim:'A claim',verification:'verified'}],evidence:result.evidence,bibliography:[{id:'doc-1',title:'Synthetic source',type:'misc'}]};
  const html=render(run,result,reportData);
  assert.match(html,/status-partial/);
  assert.equal((html.match(/class="progress-(?:done|warning|active|unknown)"/g)||[]).length,6);
  assert.match(html,/class="progress-warning"[^>]*>[\s\S]*?Verify/);
  assert.match(html,/Evidence items/);
  assert.match(html,/Evidence items: 2/);
  assert.doesNotMatch(html,/Patent Compare/);
});

test('source complete and issue open statuses are localized known states, not review actions',()=>{
  const run={run_id:'run-1',status:'partial',coverage:{complete:true,queries:[{source:'source-1',query:'query',status:'complete',candidate_count:2}]}};
  const result={outcome:'partial',issues:[{code:'ISSUE-1',status:'open',reason:'Requires attention'}]};
  for(const locale of ['zh','en','ja']){
    const sources=renderInvestigationWorkspace({run,result,reportData:{evidence:[],claims:[]},tab:'sources',t,locale});
    const overview=renderInvestigationWorkspace({run,result,reportData:{evidence:[],claims:[]},tab:'overview',t,locale});
    assert.match(sources,/status-complete/);
    assert.doesNotMatch(sources,/status-unknown/);
    assert.match(overview,/status-open/);
    assert.doesNotMatch(overview,/status-unknown/);
    assert.doesNotMatch(overview,/data-investigation-action="review/);
  }
});

test('verified claims say Verified in each locale while unknown verification stays unknown',()=>{
  const run={run_id:'run-1',status:'partial'};
  const reportData={claims:[
    {claim:'Verified claim',verification:'verified'},
    {claim:'Unresolved validation',verification:'awaiting_validation'},
  ],evidence:[]};
  for(const locale of ['zh','en','ja']){
    const html=renderInvestigationWorkspace({run,result:{outcome:'partial'},reportData,tab:'evidence',t,locale});
    assert.match(html,/status-partial/);
    assert.match(html,/status-verified/);
    assert.ok(html.includes(t('status.verified',{},locale)));
    assert.match(html,/status-unknown/);
    assert.ok(html.includes(t('status.unknown',{status:'awaiting_validation'},locale)));
    assert.doesNotMatch(html,/status-completed/);
  }
});

test('structured evidence links to the existing reader using the canonical evidence identity',()=>{
  const html=renderInvestigationWorkspace({run:{run_id:'r1'},result:{outcome:'partial',evidence:[{evidence_id:'ev-1',document_id:'doc-1',text:'Quoted source',locator:{kind:'page',value:3}}]},reportData:{bibliography:[{id:'doc-1',title:'Source'}]},tab:'evidence',t,locale:'en'});
  assert.match(html,/Quoted source/);
  assert.match(html,/data-evidence-id="ev-1"/);
  assert.match(html,/page · 3/);
});

test('Investigation navigation copy exists in all supported locales',()=>{
  for(const locale of ['zh','en','ja']){
    const html=render({run_id:'r1',status:'waiting'},null,null,locale);
    assert.match(html,/data-investigation-tab="sources"/);
    assert.match(html,/data-open-investigation-report/);
    assert.ok(!html.includes('investigation.tabSources'));
  }
});
