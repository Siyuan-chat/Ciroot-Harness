import test from 'node:test';
import assert from 'node:assert/strict';
import {fetchInvestigationList,isCurrentInvestigationResponse,projectInvestigationProgress,renderInvestigationList,renderInvestigationWorkspace} from './pages/investigation.js';
import {t} from './i18n.js';

const scope={workspaceId:'workspace-a',libraryId:'library-a',collectionId:'collection-a'};

test('investigation list loading uses the selected scope and supports paged API envelopes',async()=>{
  let args;
  const value=await fetchInvestigationList({runs:async(...input)=>{args=input;return {items:[{run_id:'inv-a'}],next_cursor:'cursor'}}},scope);
  assert.deepEqual(args,[null,scope]);
  assert.deepEqual(value,{runs:[{run_id:'inv-a'}],next:'cursor'});
});

test('stale or cross-scope investigation responses are rejected',()=>{
  const base={scope,currentScope:scope,runId:'inv-a',selectedRunId:'inv-a',responseRunId:'inv-a',generation:2,currentGeneration:2};
  assert.equal(isCurrentInvestigationResponse(base),true);
  assert.equal(isCurrentInvestigationResponse({...base,responseRunId:'inv-b'}),false);
  assert.equal(isCurrentInvestigationResponse({...base,currentGeneration:3}),false);
  assert.equal(isCurrentInvestigationResponse({...base,currentScope:{...scope,libraryId:'library-b'}}),false);
});

test('progress projection tolerates sparse and Golden Demo stage traces without inventing counts',()=>{
  const unknown=projectInvestigationProgress({run:{stage_trace:[{event:'planned'},null]},coverage:null,evidenceDocuments:null,claims:null,issues:null,outcome:null});
  assert.equal(unknown.every(step=>step.state==='unknown'),true);
  assert.equal(unknown.every(step=>step.detail===null),true);
  const projected=projectInvestigationProgress({run:{stage:'completed',status:'partial',stage_trace:[
    {node:'planning_gate',event:'planned'},{node:'source_task',event:'screened'},
    {node:'acquire_normalize',event:'normalized'},{node:'analysis_task',event:'analyzed'},
    {node:'verification_gate',event:'verified'}]},coverage:{queries:[{status:'complete'}]},
    evidenceDocuments:2,claims:[{verification:'verified'},{verification:'verified'}],
    issues:[{code:'RH_NORMALIZE_XML',status:'open'}],outcome:'partial'});
  assert.equal(projected.find(step=>step.key==='read').state,'warning');
  assert.equal(projected.find(step=>step.key==='read').detail.count,2);
  assert.equal(projected.find(step=>step.key==='verify').state,'done');
  assert.equal(projected.find(step=>step.key==='verify').detail.count,2);
  assert.equal(projected.find(step=>step.key==='review').state,'warning');
});

test('Golden Demo workspace preserves partial and synthetic state, real counts, structured claims, and no heuristic patent tab',()=>{
  const run={run_id:'inv-golden',project_id:'golden-project',status:'partial',stage:'completed',synthetic:true,
    coverage:{complete:false,candidate_count:3,queries:[{source:'synthetic-paper',status:'complete',query:'membrane',candidate_count:2}]},
    stage_trace:[{node:'planning_gate',event:'planned'},{node:'source_task',event:'screened'},{node:'acquire_normalize',event:'normalized'}]};
  const result={outcome:'partial',synthetic:true,issues:[{code:'RH_NORMALIZE_XML',status:'open',reason:'A source XML item needs normalization review.'}]};
  const reportData={research_question:'Compare membrane routes',bibliography:[
    {id:'doc-a',document_id:'doc-a',title:'Patent-like title, but not typed as a patent',type:'misc'},
    {id:'doc-b',document_id:'doc-b',title:'Synthetic paper',type:'article'}],
    evidence:[
      {evidence_id:'e1',document_id:'doc-a',version_id:'v1',locator:{kind:'paragraph',value:2},text:'Synthetic quote <unsafe>'},
      {evidence_id:'e2',document_id:'doc-a',version_id:'v1',locator:{kind:'paragraph',value:3},text:'Second evidence item'},
      {evidence_id:'e3',document_id:'doc-b',version_id:'v1',locator:{kind:'paragraph',value:1},text:'Third evidence item'}],
    claims:[{claim_id:'c1',claim:'Supported claim',verification:'verified',evidence_refs:['e1','e2']},
      {claim_id:'c2',claim:'Second supported claim',verification:'verified',evidence_refs:['e3']} ]};
  const html=renderInvestigationWorkspace({run,result,reportData,t: (key,params,locale)=>t(key,params,locale),locale:'en'});
  assert.match(html,/status-partial/);
  assert.match(html,/Synthetic data/);
  assert.match(html,/Candidates: 3/);
  assert.match(html,/2 evidence-bearing documents/);
  assert.match(html,/2 verified/);
  assert.match(html,/1 open issue/);
  assert.match(html,/Verified/);
  assert.doesNotMatch(html,/\bPatents\b/);
  assert.doesNotMatch(html,/data-investigation-action/);
  const evidenceHtml=renderInvestigationWorkspace({run,result,reportData,t,locale:'en',tab:'evidence'});
  assert.match(evidenceHtml,/Synthetic quote &lt;unsafe&gt;/);
  assert.match(evidenceHtml,/data-evidence-id="e1"/);
  assert.match(evidenceHtml,/Evidence 2/);
  const patent=renderInvestigationWorkspace({run,result,reportData:{...reportData,bibliography:[...reportData.bibliography,{id:'pat-1',title:'Registered patent',type:'patent'}]},t,locale:'en'});
  assert.match(patent,/\bPatents\b/);
});

test('unknown report fields remain unknown and the investigation UI has EN, zh-CN and JA labels',()=>{
  const unknownHtml=renderInvestigationWorkspace({run:{run_id:'inv-unknown',status:'waiting'},result:null,reportData:null,t,locale:'en'});
  assert.match(unknownHtml,/Unknown/);
  assert.doesNotMatch(unknownHtml,/>0</);
  const locales=[['en','Investigations','Sources','Evidence & Claims','Activity'],['zh','调查','来源','证据与主张','活动'],['ja','調査','ソース','証拠と主張','アクティビティ']];
  for(const [locale,...labels] of locales){
    const html=renderInvestigationList({runs:[{run_id:'inv-a',status:'partial',stage:'source'}],t,locale});
    assert.ok(labels[0]&&html.includes(labels[0]));
    const workspace=renderInvestigationWorkspace({run:{run_id:'inv-a',status:'partial'},result:null,reportData:null,t,locale});
    assert.ok(workspace.includes(labels[1]));assert.ok(workspace.includes(labels[2]));assert.ok(workspace.includes(labels[3]));
  }
});
