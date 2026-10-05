import test from 'node:test';
import assert from 'node:assert/strict';
import { api, request, ApiError, setToken, stableTurnIdentity, conversationExecutorSwitchBody } from './api.js';

globalThis.document = { querySelector: () => ({ content: 'local-token' }) };
test('same-origin reads and writes use contract path, token and idempotency key', async () => {
  setToken('local-token');
  const calls=[];
  globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({schema_version:'1',items:[]})}};
  await api.library(); await api.advance('run/1');
  assert.equal(calls[0].url,'/api/v1/library?limit=50');
  assert.equal(Object.hasOwn(calls[0].options.headers,'x-session-token'),false);
  assert.equal(calls[1].url,'/api/v1/runs/run%2F1/advance');
  assert.equal(calls[1].options.headers['x-session-token'],'local-token');
  assert.ok(calls[1].options.headers['idempotency-key']);
});
test('review inbox is a bounded scoped read and does not send write or idempotency metadata',async()=>{
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({schema_version:'1',items:[],unavailable_runs:[],next_cursor:null})}};
  const scope={workspaceId:'ws-review',libraryId:'lib-review',collectionId:'collection-review'};
  await api.reviewInbox('Y3Vyc29y',scope,50);
  const {url,options}=calls[0];
  assert.equal(url,'/api/v1/review-inbox?limit=50&cursor=Y3Vyc29y');
  assert.equal(options.method,'GET');
  assert.equal(options.headers['X-Workspace-Id'],scope.workspaceId);
  assert.equal(options.headers['X-Library-Id'],scope.libraryId);
  assert.equal(options.headers['X-Collection-Id'],scope.collectionId);
  assert.equal(Object.hasOwn(options.headers,'idempotency-key'),false);
  assert.equal(options.body,undefined);
});
test('mutations retain the initiating project and library scope after a UI context switch',async()=>{
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({schema_version:'1'})}};
  await api.advance('run-a',{workspaceId:'project-a',libraryId:'library-a',collectionId:'group-a'});
  assert.equal(calls[0].options.headers['X-Workspace-Id'],'project-a');
  assert.equal(calls[0].options.headers['X-Library-Id'],'library-a');
  assert.equal(calls[0].options.headers['X-Collection-Id'],'group-a');
});
test('workspace creation is unscoped, authenticated, idempotency-keyed and excludes filesystem paths',async()=>{
  setToken('create-token');
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({schema_version:'1',workspace_id:'ws-1'})}};
  await api.createWorkspace('New workspace','optional note',['lib-1'],'workspace-request-1');
  const {url,options}=calls[0];
  assert.equal(url,'/api/v1/workspaces');
  assert.equal(options.method,'POST');
  assert.equal(options.headers['x-session-token'],'create-token');
  assert.equal(options.headers['idempotency-key'],'workspace-request-1');
  assert.equal(Object.hasOwn(options.headers,'X-Workspace-Id'),false);
  assert.deepEqual(JSON.parse(options.body),{name:'New workspace',description:'optional note',reference_library_ids:['lib-1']});
});
test('conversation API reads top-level create response then fetches full conversation before scoped turn',async()=>{
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,options});const data=url==='/api/v1/conversations'?{schema_version:'1',conversation_id:'con-1'}:url==='/api/v1/conversations/con-1'?{schema_version:'1',conversation:{conversation_id:'con-1',executor:'scripted',messages:[]}}:{schema_version:'1',conversation:{conversation_id:'con-1',messages:[{role:'user',content:'Question text'}]}};return {ok:true,status:200,json:async()=>data}};
  const scope={workspaceId:'ws-a',libraryId:'lib-a',collectionId:'all'};
  const created=await api.createConversation('scripted',scope,undefined,'create-1');
  assert.equal(created.conversation.conversation_id,'con-1');
  await api.conversationTurn('con-1','Question text','turn-1',scope);
  await api.executeConversation('con-1','scripted',undefined,scope,'execute-1');
  await api.stopConversation('con-1','investigation',scope);
  assert.equal(calls[0].url,'/api/v1/conversations');
  assert.deepEqual(JSON.parse(calls[0].options.body),{executor:'scripted',fixture_id:'synthetic-d19'});
  assert.equal(calls[0].options.headers['idempotency-key'],'create-1');
  assert.equal(calls[1].url,'/api/v1/conversations/con-1');
  assert.equal(calls[2].url,'/api/v1/conversations/con-1/turns');
  assert.deepEqual(JSON.parse(calls[2].options.body),{request_id:'turn-1',content:'Question text'});
  assert.equal(calls[3].options.headers['idempotency-key'],'execute-1');
  assert.deepEqual(JSON.parse(calls[3].options.body),{});
  assert.deepEqual(JSON.parse(calls[4].options.body),{kind:'investigation'});
  for(const call of calls)assert.equal(call.options.headers['X-Workspace-Id'],'ws-a');
});
test('external conversations read top-level create and keep waiting turns scoped',async()=>{
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,options});const data=url==='/api/v1/conversations'?{schema_version:'1',conversation_id:'con-ext'}:url==='/api/v1/conversations/con-ext'?{schema_version:'1',conversation:{conversation_id:'con-ext',status:'awaiting_input'}}:{schema_version:'1',conversation:{conversation_id:'con-ext',status:'waiting_external'}};return {ok:true,status:200,json:async()=>data}};
  const scope={workspaceId:'ws-ext',libraryId:'lib-ext',collectionId:'all'};
  await api.createConversation('external',scope);
  await api.conversationTurn('con-ext','Run this question','turn-ext',scope);
  assert.deepEqual(JSON.parse(calls[0].options.body),{executor:'external'});
  assert.equal(calls[1].url,'/api/v1/conversations/con-ext');
  assert.equal(calls[2].url,'/api/v1/conversations/con-ext/turns');
  assert.equal(calls[2].options.headers['X-Workspace-Id'],'ws-ext');
  assert.deepEqual(JSON.parse(calls[2].options.body),{request_id:'turn-ext',content:'Run this question'});
});
test('executor switch updates the existing scoped conversation idempotently',async()=>{
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,options});const summary={conversation_id:'con-existing',executor:'api',status:'awaiting_input'};const full={...summary,messages:[{role:'user',content:'kept'},{role:'progress',content:'run bound',refs:{run_id:'inv-real'}}],tool_results:[{object_refs:{run_id:'inv-real',command_id:'cmd-real'}}]};return {ok:true,status:200,json:async()=>url.endsWith('/executor')?{schema_version:'1',conversation:summary}:{schema_version:'1',conversation:full}}};
  const scope={workspaceId:'ws-a',libraryId:'lib-a',collectionId:'all'};
  const result=await api.switchConversationExecutor('con-existing','external',scope,'switch-request-1');
  assert.equal(calls[0].url,'/api/v1/conversations/con-existing/executor');
  assert.equal(calls[0].options.method,'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body),{executor:'external'});
  assert.equal(calls[0].options.headers['idempotency-key'],'switch-request-1');
  assert.equal(calls[0].options.headers['X-Workspace-Id'],'ws-a');
  assert.equal(calls[1].url,'/api/v1/conversations/con-existing');
  assert.equal(calls[1].options.method,'GET');
  assert.equal(calls[1].options.headers['X-Workspace-Id'],'ws-a');
  assert.equal(result.conversation.conversation_id,'con-existing');
  assert.equal(result.conversation.messages[0].content,'kept');
  assert.equal(result.conversation.tool_results[0].object_refs.command_id,'cmd-real');
});
test('executor switch preserves backend 409 busy rejection',async()=>{
  globalThis.fetch=async()=>({ok:false,status:409,json:async()=>({code:'RH_GUI_EXTERNAL_TURN_PENDING',message:'pending',retryable:true})});
  await assert.rejects(api.switchConversationExecutor('con-existing','api',{workspaceId:'ws-a',libraryId:'lib-a',collectionId:'all'},'switch-request-2'),error=>error instanceof ApiError&&error.status===409&&error.code==='RH_GUI_EXTERNAL_TURN_PENDING');
});
test('API executor switching sends bounded config in place and preserves API identity',async()=>{
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,options});const value={conversation_id:'con-existing',executor:'api',api:{provider:'openai',model:'fake',total_model_calls:5},messages:[{content:'preserved'}],tool_results:[{object_refs:{run_id:'run-retained'}}]};return {ok:true,status:200,json:async()=>({schema_version:'1',conversation:value})}};
  const config={provider:'openai',model:'fake',max_planning_calls:2,max_output_tokens:512,timeout_seconds:30,total_model_calls:5,runtime_template:{mode:'api',data_mode:'synthetic',allow_network:true,model_api:{provider:'openai',model:'fake',api_key_env:'OPENAI_API_KEY',max_output_tokens:512,timeout_seconds:30},budget:{max_model_calls:5}}};
  const scope={workspaceId:'ws-a',libraryId:'lib-a',collectionId:'all'};
  const result=await api.switchConversationExecutor('con-existing','api',scope,'switch-api-1',config);
  assert.deepEqual(JSON.parse(calls[0].options.body),{executor:'api',api_config:config});
  assert.equal(calls[0].options.headers['idempotency-key'],'switch-api-1');
  assert.equal(calls[0].url,'/api/v1/conversations/con-existing/executor');
  assert.equal(result.conversation.conversation_id,'con-existing');
  assert.equal(result.conversation.messages[0].content,'preserved');
  assert.equal(result.conversation.tool_results[0].object_refs.run_id,'run-retained');
  assert.deepEqual(conversationExecutorSwitchBody('scripted'),{executor:'scripted',fixture_id:'synthetic-d19'});
});
test('API configuration expansion conflict code is retained for a precise UI message',async()=>{
  globalThis.fetch=async()=>({ok:false,status:409,json:async()=>({detail:'RH_GUI_API_CONFIG_EXPANSION: API executor configuration cannot expand limits'})});
  await assert.rejects(api.switchConversationExecutor('con-existing','api',{workspaceId:'ws-a',libraryId:'lib-a',collectionId:'all'},'switch-api-2',{provider:'openai'}),error=>error instanceof ApiError&&error.status===409&&error.code==='RH_GUI_API_CONFIG_EXPANSION');
});
test('turn request identity is stable for retries and changes with content or scope',()=>{
  const scope={workspaceId:'ws-a',libraryId:'lib-a',collectionId:'all'};
  const first=stableTurnIdentity('same text',scope,null);
  assert.equal(stableTurnIdentity('same text',scope,first).requestId,first.requestId);
  assert.notEqual(stableTurnIdentity('edited text',scope,first).requestId,first.requestId);
  assert.notEqual(stableTurnIdentity('same text',{...scope,libraryId:'lib-b'},first).requestId,first.requestId);
});
test('typed errors stay visible and schema mismatch is rejected',async()=>{
  globalThis.fetch=async()=>({ok:false,status:409,json:async()=>({code:'RH_BUSY',message:'工作区繁忙',retryable:true,request_id:'r1'})});
  await assert.rejects(request('/runs'),e=>e instanceof ApiError&&e.code==='RH_BUSY'&&e.retryable);
  globalThis.fetch=async()=>({ok:true,status:200,json:async()=>({schema_version:'2'})});
  await assert.rejects(request('/runs'),e=>e.code==='RH_SCHEMA_VERSION');
});
test('event cursor and original locator are encoded for the local API',async()=>{
  const urls=[];
  globalThis.fetch=async(url)=>{urls.push(url);return {ok:true,status:200,json:async()=>({schema_version:'1'})}};
  await api.events('inv/1',42);
  await api.locate('inv/1','doc/2',{kind:'xml_node',value:'/claims/claim[16]'});
  assert.equal(urls[0],'/api/v1/runs/inv%2F1/events?after=42&limit=100');
  assert.ok(urls[1].includes('value=%2Fclaims%2Fclaim%5B16%5D'));
});

test('queue GETs send a session token when present and preserve missing-token rejection',async()=>{
  setToken('queue-token');
  const calls=[];
  globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({schema_version:'1',items:[]})}};
  await api.commandQueue();
  await api.command('cmd-1');
  assert.equal(calls[0].options.headers['x-session-token'],'queue-token');
  assert.equal(calls[1].options.headers['x-session-token'],'queue-token');

  setToken('');
  globalThis.document={querySelector:()=>null};
  globalThis.fetch=async(url,options)=>{
    assert.equal(Object.hasOwn(options.headers,'x-session-token'),false);
    return {ok:false,status:403,json:async()=>({code:'RH_GUI_TOKEN',message:'session token is required'})};
  };
  await assert.rejects(api.commandQueue(),error=>error instanceof ApiError&&error.status===403&&error.code==='RH_GUI_TOKEN');
  await assert.rejects(api.command('cmd-1'),error=>error instanceof ApiError&&error.status===403&&error.code==='RH_GUI_TOKEN');
});

test('managed view control subscribes and reads events with identity, current scope and session token',async()=>{
  setToken('view-token');
  const calls=[];globalThis.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,json:async()=>({schema_version:'1',connected:true,events:[],next_seq:0})}};
  const selected={workspaceId:'ws-2',libraryId:'lib-3',collectionId:'group-4'};
  await api.control('view.subscribe',{client_id:'tab-1'},selected);
  await api.controlEvents('tab-1',7,selected);
  assert.equal(calls[0].url,'/api/v1/control');
  assert.equal(calls[0].options.headers['x-session-token'],'view-token');
  assert.equal(calls[0].options.headers['X-Workspace-Id'],'ws-2');
  const body=JSON.parse(calls[0].options.body);
  assert.equal(body.action,'view.subscribe');assert.equal(body.payload.client_id,'tab-1');assert.equal(body.scope.collection_id,'group-4');assert.ok(body.actor);assert.ok(body.request_id);
  assert.equal(calls[1].url,'/api/v1/control/clients/tab-1/events?after=7');
  assert.equal(calls[1].options.headers['x-session-token'],'view-token');
});
