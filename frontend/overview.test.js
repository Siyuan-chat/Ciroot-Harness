import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {t} from './i18n.js';
import {api} from './api.js';
import {renderOverview} from './pages/overview.js';

const app=await readFile(new URL('./app.js',import.meta.url),'utf8');
const apiSource=await readFile(new URL('./api.js',import.meta.url),'utf8');

test('Overview is the default route and exposes only four product destinations plus Settings',()=>{
  assert.match(app,/page: 'overview'/);
  assert.match(app,/const nav = \[\['overview','nav\.overview'\],\['library','nav\.library'\],\['investigations','nav\.investigations'\],\['reports','nav\.reportsReview'\],\['settings','nav\.settings'\]\]/);
  assert.match(app,/nav\.slice\(0,4\)/);
  assert.match(app,/nav\.slice\(4\)/);
  assert.doesNotMatch(app,/\['reader','|\['patents','/);
  assert.match(app,/const publicPage=\(\{report:'reports',reviews:'reports',runs:'investigations',reader:'library',patents:'investigations'\}\[state\.page\]\|\|state\.page\)/);
  assert.match(app,/aria-current=\"\$\{publicPage===id\?'page':'false'\}\"/);
  assert.match(app,/const shellPageHead=\['overview','investigations','reports','report'\]\.includes\(state\.page\)\?'':/);
});

test('Overview keeps unknown counts nullable and labels Golden Demo offline and synthetic',()=>{
  const html=renderOverview({overview:{workspace:{name:'Polymer'},library:{index_status:'unindexed',document_count:null},recent_runs:[{run_id:'inv-1',outcome:'partial',verified_claim_count:null,open_issue_count:null}],review_summary:{open_run_issue_count:null}},locale:'en',t});
  assert.match(html,/OFFLINE/);assert.match(html,/SYNTHETIC/);assert.match(html,/NO API KEY/);
  assert.match(html,/Documents: Unknown/);assert.match(html,/Verified claims: Unknown/);assert.match(html,/Open issues: Unknown/);
  assert.doesNotMatch(html,/0 documents|0 verified claims|0 open issues/);
  assert.match(html,/data-golden-demo/);assert.match(html,/data-open-overview-run="inv-1"/);
});

test('Plan keeps the question in the current scoped draft and opens assistant without a request',()=>{
  const plan=app.match(/function planInvestigation\(\)\{([\s\S]*?)\}\r?\nasync function openOverviewRun/)?.[1]||'';
  assert.match(plan,/conversationScopeKey\(scope,state\.conversation\?\.conversation_id\|\|'draft'\)/);
  assert.match(plan,/state\.chatDrafts\.set\(key,question\)/);
  assert.match(plan,/state\.chatOpen=true/);
  assert.doesNotMatch(plan,/api\.|conversationTurn|executeConversation/);
  assert.match(app,/chatOpen:false/);
});

test('Golden Demo uses scoped idempotent adapter then opens the real returned run',()=>{
  const handler=app.match(/async function startGoldenDemo\(\)\{([\s\S]*?)\}\r?\nasync function loadLibrary/)?.[1]||'';
  assert.match(handler,/api\.runGoldenDemoScoped\(scope,key\)/);
  assert.match(handler,/await openInvestigation\(runId\)/);
  const open=app.match(/async function openInvestigation\(runId\)\{([\s\S]*?)\}\r?\nasync function startGoldenDemo/)?.[1]||'';
  assert.match(open,/api\.run\(runId,scope\)/);
  assert.match(open,/api\.tasks\(runId,scope\)/);
  assert.match(open,/state\.page='investigations'/);
  assert.match(handler,/demoIdempotencyKey/);
  assert.match(apiSource,/runGoldenDemoScoped: \(requestScope,idempotencyKey\) => request\('\/demos\/golden'/);
});

test('Overview and scoped Demo requests preserve the selected scope and Demo idempotency key',async()=>{
  const oldFetch=globalThis.fetch,oldDocument=globalThis.document,calls=[];
  globalThis.document={querySelector:()=>null};
  globalThis.fetch=async(url,init)=>{calls.push({url,init});return {ok:true,status:200,json:async()=>({schema_version:'1',run_id:'inv-1'})}};
  try{
    const scope={workspaceId:'workspace-a',libraryId:'library-b',collectionId:'collection-c'};
    await api.overview(scope);await api.runGoldenDemoScoped(scope,'idem-key');
    assert.equal(calls[0].url,'/api/v1/overview');assert.equal(calls[0].init.headers['X-Workspace-Id'],'workspace-a');
    assert.equal(calls[1].url,'/api/v1/demos/golden');assert.equal(calls[1].init.headers['X-Library-Id'],'library-b');
    assert.equal(calls[1].init.headers['X-Collection-Id'],'collection-c');assert.equal(calls[1].init.headers['idempotency-key'],'idem-key');
    assert.equal(calls[1].init.body,'{}');
  }finally{globalThis.fetch=oldFetch;globalThis.document=oldDocument}
});
