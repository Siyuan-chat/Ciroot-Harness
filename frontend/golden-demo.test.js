import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { api, goldenDemoIdentity } from './api.js';
import { goldenDemoCtaLabel, renderGoldenDemo } from './golden-demo-view.js';

const fixture={schema_version:'1',demo:{workspace_label:'Golden Demo',run_id:'demo-run-7',status:{status:'partial',stage:'completed',outcome:'partial',stage_trace:[{node:'acquire_normalize',event:'source_failure',code:'RH_NORMALIZE_XML',status:'open',document_id:'paper-review-gap',version_id:'v1',message:'invalid XML'}],coverage:{complete:true,queries:[{query_id:'q1',source:'synthetic-paper',status:'complete',query:'paper query'},{query_id:'q2',source:'synthetic-patent',status:'complete',query:'patent query'}],attempts:[{query_id:'q1',attempt:1,status:'success'},{query_id:'q2',attempt:1,status:'success'}]},synthetic:true},spec:{research_question:'Synthetic question',status:'ready',project_id:'synthetic-d19',revision:1,report_targets:['technical_report','literature_review'],references:[]},result:{issues:[{code:'RH_NORMALIZE_XML',status:'open',document_id:'paper-review-gap',version_id:'v1',message:'invalid XML'}],evidence:[{evidence_id:'ev-1',document_id:'doc-1',version_id:'ver-3',locator:{page:2},text:'Source excerpt'}]},report_data:{claims:[{claim_id:'claim-1',claim:'Supported claim',evidence_refs:['ev-1']}],evidence:[{evidence_id:'ev-1',document_id:'doc-1',version_id:'ver-3',locator:{page:2},text:'Source excerpt'}],sections:[{title:'Findings',body:'Finding body'}],coverage:{queries:[{query_id:'q1',query:'duplicate query'}],attempts:[{query_id:'q1',attempt:2,status:'duplicate'}]}},reports:[{type:'technical_report',language:'en',format:'markdown',content:'Technical body'},{type:'literature_review',language:'en',format:'markdown',content:'Review body'}]}};

test('Golden Demo CTA uses one localized label in the workspace shell',async()=>{
  const app=await readFile(new URL('./app.js',import.meta.url),'utf8');
  assert.ok(app.includes(`id="top-demo" class="primary" data-open-golden-demo`));
  assert.match(app,/function openGoldenDemo\(\)/);
  for(const [locale,expected] of [['en','Try Offline Demo'],['zh','体验离线 Demo'],['ja','オフライン Demo を試す']]){
    assert.equal(goldenDemoCtaLabel(locale),expected);
    assert.doesNotMatch(renderGoldenDemo({locale}),/Try Offline Demo · 体验离线 Demo · オフライン Demo/);
  }
});

test('Golden Demo API is isolated from selected library and POST body/key are canonical',async()=>{
  const calls=[];
  const previous=globalThis.fetch;
  const previousDocument=globalThis.document;
  const store=new Map();
  const previousStorage=globalThis.localStorage;
  globalThis.localStorage={getItem:key=>store.get(key)||null,setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)};
  globalThis.document={querySelector:()=>null};
  globalThis.fetch=async(url,init)=>{calls.push({url,init});return {ok:true,status:200,json:async()=>fixture}};
  try {
    await api.readGoldenDemo();
    const key=goldenDemoIdentity();
    await api.runGoldenDemo(key);
    assert.equal(calls[0].url,'/api/v1/golden-demo');
    assert.equal(calls[0].init.headers['X-Workspace-Id'],undefined);
    assert.equal(calls[1].url,'/api/v1/golden-demo');
    assert.equal(calls[1].init.headers['X-Library-Id'],undefined);
    assert.equal(calls[1].init.headers['idempotency-key'],key);
    assert.deepEqual(JSON.parse(calls[1].init.body),{});
    assert.equal(goldenDemoIdentity(),key);
    assert.notEqual(goldenDemoIdentity(true),key);
  } finally {globalThis.fetch=previous;globalThis.localStorage=previousStorage;globalThis.document=previousDocument}
});

test('renderer binds status, evidence, review issues, reports and escapes returned content',()=>{
  const html=renderGoldenDemo({locale:'en',demo:fixture.demo,tab:'overview'});
  assert.match(html,/SYNTHETIC[\s\S]*OFFLINE[\s\S]*DEMO/);
  assert.match(html,/demo-run-7/);
  assert.match(html,/Partial.*incomplete coverage/);
  assert.match(html,/\b1\b/);
  const evidence=renderGoldenDemo({locale:'en',demo:fixture.demo,tab:'evidence',selectedClaim:0});
  assert.match(evidence,/data-demo-evidence="ev-1"/);
  assert.match(evidence,/doc-1/);assert.match(evidence,/ver-3/);assert.match(evidence,/Source excerpt/);
  const review=renderGoldenDemo({locale:'en',demo:fixture.demo,tab:'review'});
  assert.match(review,/RH_NORMALIZE_XML/);assert.match(review,/paper-review-gap/);assert.match(review,/v1/);assert.match(review,/invalid XML/);assert.match(review,/Open/);
  const sources=renderGoldenDemo({locale:'en',demo:fixture.demo,tab:'sources'});
  assert.match(sources,/paper query/);assert.match(sources,/patent query/);assert.doesNotMatch(sources,/duplicate query/);
  assert.equal((sources.match(/synthetic-paper/g)||[]).length,1);assert.equal((sources.match(/success/g)||[]).length,2);
  const reports=renderGoldenDemo({locale:'en',demo:fixture.demo,tab:'reports'});
  assert.match(reports,/technical_report/);assert.match(reports,/Technical body/);assert.match(reports,/literature_review/);assert.match(reports,/Review body/);
  const hostile=structuredClone(fixture.demo);hostile.reports[0].content='<img src=x onerror="alert(1)">';
  hostile.result.evidence[0].text='<script>run()</script>';
  const safe=renderGoldenDemo({locale:'en',demo:hostile,tab:'reports'});
  assert.doesNotMatch(safe,/<img|<script>/);assert.match(safe,/&lt;img/);
});

test('failed demo POST can retry with persisted same idempotency identity',async()=>{
  const previous=globalThis.fetch,previousStorage=globalThis.localStorage,previousDocument=globalThis.document,store=new Map(),keys=[];
  globalThis.localStorage={getItem:key=>store.get(key)||null,setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)};
  globalThis.document={querySelector:()=>null};
  globalThis.fetch=async(_url,init)=>{keys.push(init.headers['idempotency-key']);return {ok:false,status:503,json:async()=>({detail:'temporary'})}};
  try {const first=goldenDemoIdentity();await assert.rejects(api.runGoldenDemo(first));const retry=goldenDemoIdentity();await assert.rejects(api.runGoldenDemo(retry));assert.equal(keys[0],keys[1])}
  finally {globalThis.fetch=previous;globalThis.localStorage=previousStorage;globalThis.document=previousDocument}
});

test('all demo tabs retain the badge and localized titles; failed and completed states stay distinct',()=>{
  for(const locale of ['en','zh','ja'])for(const tab of ['overview','spec','sources','evidence','review','reports'])assert.match(renderGoldenDemo({locale,demo:fixture.demo,tab}),/SYNTHETIC[\s\S]*OFFLINE[\s\S]*DEMO/);
  const failed=structuredClone(fixture.demo);failed.status.status='failed';
  const completed=structuredClone(fixture.demo);completed.status.status='completed';
  assert.match(renderGoldenDemo({demo:failed}),/Failed/);assert.match(renderGoldenDemo({demo:completed}),/Completed/);
});
