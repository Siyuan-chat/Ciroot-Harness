const ROOT = '/api/v1';
export class ApiError extends Error {
  constructor(body, status) { const detail=typeof body?.detail==='string'?body.detail:'';const match=detail.match(/^([A-Z][A-Z0-9_]+):(.*)$/s);super(body?.message||detail||`请求失败 (${status})`);this.name='ApiError';this.code=body?.code||match?.[1]||'HTTP_ERROR';this.status=status;this.retryable=!!body?.retryable;this.requestId=body?.request_id||null; }
}
let sessionToken = '';
let scope = { workspaceId: 'default', libraryId: 'default', collectionId: 'all' };
export function setToken(value) { sessionToken = value || ''; }
export function setScope(value) { scope = { ...scope, ...value }; }
export function token() { return sessionToken || document.querySelector('meta[name="rh-session-token"]')?.content || ''; }
export function stableTurnIdentity(content, requestScope, previous) {
  const scopeKey = [requestScope?.workspaceId, requestScope?.libraryId, requestScope?.collectionId].join('\u0000');
  if (previous?.content === content && previous?.scopeKey === scopeKey) return previous;
  return { content, scopeKey, requestId: crypto.randomUUID() };
}
export function conversationIdFromCreate(data) {
  const id = data?.conversation_id;
  if (typeof id !== 'string' || !id) throw new ApiError({code:'RH_GUI_CONVERSATION_CREATE_RESPONSE',message:'创建会话响应缺少 conversation_id'},200);
  return id;
}
export function conversationCreateBody(executor, apiConfig) { return {executor, ...(executor==='scripted'?{fixture_id:'synthetic-d19'}:{}), ...(executor==='api'?{api_config:apiConfig}:{})}; }
export function conversationExecutorSwitchBody(executor, apiConfig) { return {executor, ...(executor==='scripted'?{fixture_id:'synthetic-d19'}:{}), ...(executor==='api'?{api_config:apiConfig}:{})}; }
export function conversationExecutionBody(executor, scenario) { return executor==='api'?{scenario,confirm_api_execution:true}:{}; }
export async function request(path, { method = 'GET', body, signal, unscoped = false, requestScope, includeSessionToken = false, idempotencyKey } = {}) {
  const headers = { Accept: 'application/json' };
  if(!unscoped){const selected=requestScope||scope;headers['X-Workspace-Id'] = selected.workspaceId;headers['X-Library-Id'] = selected.libraryId;headers['X-Collection-Id'] = selected.collectionId;}
  if (body !== undefined) { headers['Content-Type'] = 'application/json'; headers['idempotency-key'] = idempotencyKey || crypto.randomUUID(); }
  if (body !== undefined || includeSessionToken) {
    const value=token();
    if(value) headers['x-session-token']=value;
  }
  const response = await fetch(ROOT + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal, credentials: 'same-origin' });
  if (!response.ok) { let data; try { data = await response.json(); } catch { data = null; } throw new ApiError(data, response.status); }
  if (response.status === 204) return { schema_version: '1' };
  const data = await response.json();
  if (data?.schema_version !== '1') throw new ApiError({ code: 'RH_SCHEMA_VERSION', message: '接口版本不匹配' }, response.status);
  return data;
}
export async function uploadLibraryFile(file, requestScope) {
  const selected=requestScope||scope;
  const headers={'Accept':'application/json','Content-Type':'application/octet-stream','X-Workspace-Id':selected.workspaceId,'X-Library-Id':selected.libraryId,'X-Collection-Id':selected.collectionId,'idempotency-key':crypto.randomUUID()};
  const value=token();if(value)headers['x-session-token']=value;
  const response=await fetch(`${ROOT}/library/import?filename=${encodeURIComponent(file.name)}`,{method:'PUT',headers,body:file,credentials:'same-origin'});
  if(!response.ok){let data;try{data=await response.json()}catch{data=null}throw new ApiError(data,response.status)}
  const data=await response.json();if(data?.schema_version!=='1')throw new ApiError({code:'RH_SCHEMA_VERSION',message:'接口版本不匹配'},response.status);return data;
}

let goldenDemoRequestId = '';
export function goldenDemoIdentity(fresh=false) {
  if (fresh) goldenDemoRequestId = crypto.randomUUID();
  if (!goldenDemoRequestId) {
    try { goldenDemoRequestId = localStorage.getItem('rh-golden-demo-request') || ''; } catch {}
  }
  if (!goldenDemoRequestId) goldenDemoRequestId = crypto.randomUUID();
  try { localStorage.setItem('rh-golden-demo-request', goldenDemoRequestId); } catch {}
  return goldenDemoRequestId;
}
export const api = {
  conversations: () => request('/conversations'),
  conversation: (id, requestScope) => request(`/conversations/${encodeURIComponent(id)}`, {requestScope}),
  createConversation: async (executor, requestScope, apiConfig, idempotencyKey) => {
    const created=await request('/conversations', {method:'POST', body:conversationCreateBody(executor,apiConfig), requestScope, idempotencyKey});
    const id=conversationIdFromCreate(created);
    const full=await request(`/conversations/${encodeURIComponent(id)}`, {requestScope});
    if(full.conversation?.conversation_id!==id) throw new ApiError({code:'RH_GUI_CONVERSATION_IDENTITY',message:'conversation identity changed during creation'},200);
    return full;
  },
  switchConversationExecutor: async (id, executor, requestScope, idempotencyKey, apiConfig) => {
    await request(`/conversations/${encodeURIComponent(id)}/executor`, {method:'POST', body:conversationExecutorSwitchBody(executor,apiConfig), requestScope, idempotencyKey});
    const result=await request(`/conversations/${encodeURIComponent(id)}`, {requestScope});
    if(result.conversation?.conversation_id!==id) throw new ApiError({code:'RH_GUI_CONVERSATION_IDENTITY',message:'conversation identity changed during executor switch'},200);
    return result;
  },
  conversationTurn: (id, content, requestId, requestScope) => request(`/conversations/${encodeURIComponent(id)}/turns`, {method:'POST', body:{request_id:requestId,content}, requestScope}),
  executeConversation: (id, executor, scenario, requestScope, idempotencyKey) => request(`/conversations/${encodeURIComponent(id)}/execute`, {method:'POST', body:conversationExecutionBody(executor,scenario), requestScope, idempotencyKey}),
  stopConversation: (id, kind, requestScope) => request(`/conversations/${encodeURIComponent(id)}/stop`, {method:'POST', body:{kind}, requestScope}),
  registry: () => request('/registry',{unscoped:true}),
  createWorkspace: (name, description, referenceLibraryIds=[], idempotencyKey) => request('/workspaces',{method:'POST',unscoped:true,includeSessionToken:true,idempotencyKey,body:{name,...(description?{description}:{}),reference_library_ids:referenceLibraryIds}}),
  contexts: requestScope => request('/contexts',{requestScope}),
  libraries: workspaceId => request(`/workspaces/${encodeURIComponent(workspaceId)}/libraries`),
  collections: libraryId => request(`/libraries/${encodeURIComponent(libraryId)}/collections`),
  capabilities: () => request('/capabilities'),
  modelCredentials: () => request('/model-credentials'),
  sourceCredentials: () => request('/source-credentials'),
  setSourceCredential: (name,apiKey) => request(`/source-credentials/${encodeURIComponent(name)}`, {method:'POST',body:{api_key:apiKey}}),
  clearSourceCredential: name => request(`/source-credentials/${encodeURIComponent(name)}`, {method:'DELETE',body:{}}),
  mcpSetup: () => request('/mcp-setup'),
  setModelCredential: (provider,apiKey) => request(`/model-credentials/${encodeURIComponent(provider)}`, {method:'POST',body:{api_key:apiKey}}),
  clearModelCredential: provider => request(`/model-credentials/${encodeURIComponent(provider)}`, {method:'DELETE',body:{}}),
  quit: () => request('/desktop/quit', { method: 'POST', body: {} }),
  commandQueue: requestScope => request('/queue',{requestScope,includeSessionToken:true}),
  command: (id,requestScope) => request(`/queue/${encodeURIComponent(id)}`,{requestScope,includeSessionToken:true}),
  control: (action,payload={},requestScope) => request('/control',{method:'POST',body:{action,actor:'gui',request_id:crypto.randomUUID(),scope:{workspace_id:requestScope?.workspaceId||scope.workspaceId,library_id:requestScope?.libraryId||scope.libraryId,collection_id:requestScope?.collectionId||scope.collectionId},payload},requestScope,includeSessionToken:true}),
  controlEvents: (clientId,after=0,requestScope) => request(`/control/clients/${encodeURIComponent(clientId)}/events?after=${encodeURIComponent(after)}`,{requestScope,includeSessionToken:true}),
  cancelCommand: (id,requestScope) => request(`/queue/${encodeURIComponent(id)}/cancel`,{method:'POST',body:{},requestScope}),
  resumeQueue: (requestScope,reviewedCommandIds=[]) => request('/queue/resume',{method:'POST',body:reviewedCommandIds.length?{reviewed_command_ids:reviewedCommandIds,confirm_needs_review:true}:{},requestScope}),
  library: (cursor,requestScope) => request('/library?limit=50' + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''),{requestScope}),
  searchEvidence: (query, topK=8,requestScope) => request(`/library/search?q=${encodeURIComponent(query)}&top_k=${encodeURIComponent(topK)}`,{requestScope}),
  createLibrary: (name,requestScope,idempotencyKey) => request('/libraries',{method:'POST',body:{name},requestScope,idempotencyKey}),
  uploadLibraryFile,
  libraryDocument: (id,requestScope) => request(`/library/documents/${encodeURIComponent(id)}`,{requestScope}),
  runDocument: (runId,id,requestScope) => request(`/runs/${encodeURIComponent(runId)}/documents/${encodeURIComponent(id)}`,{requestScope}),
  runs: (cursor,requestScope) => request('/runs?limit=50' + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''),{requestScope}),
  overview: requestScope => request('/overview',{requestScope}),
  reviewInbox: (cursor, requestScope, limit=50) => request('/review-inbox?limit=' + encodeURIComponent(limit) + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''), {requestScope}),
  run: (id,requestScope) => request(`/runs/${encodeURIComponent(id)}`,{requestScope}),
  referenceSnapshot: (id,requestScope) => request(`/runs/${encodeURIComponent(id)}/reference-snapshot`,{requestScope}),
  events: (id, after=0,requestScope) => request(`/runs/${encodeURIComponent(id)}/events?after=${encodeURIComponent(after)}&limit=100`,{requestScope}),
  locate: (runId,documentId,locator,requestScope) => request(`/runs/${encodeURIComponent(runId)}/documents/${encodeURIComponent(documentId)}/locate?kind=${encodeURIComponent(locator.kind)}&value=${encodeURIComponent(locator.value)}`,{requestScope}),
  result: (id,requestScope) => request(`/runs/${encodeURIComponent(id)}/result`,{requestScope}),
  reportData: (id,requestScope) => request(`/runs/${encodeURIComponent(id)}/report-data`,{requestScope}),
  tasks: (id,requestScope) => request(`/runs/${encodeURIComponent(id)}/tasks`,{requestScope}),
  artifacts: (id,requestScope) => request(`/runs/${encodeURIComponent(id)}/artifacts`,{requestScope}),
  export: (id,languages=['zh','en'],requestScope) => request(`/runs/${encodeURIComponent(id)}/export`,{method:'POST',body:{languages},requestScope}),
  evidence: (id, runId,requestScope) => request(`/evidence/${encodeURIComponent(id)}${runId?`?run_id=${encodeURIComponent(runId)}`:''}`,{requestScope}),
  reviews: (monitorId, cursor,requestScope) => request('/reviews?limit=50' + (monitorId ? `&monitor_id=${encodeURIComponent(monitorId)}` : '') + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''),{requestScope}),
  create: (spec, runtime, scenario, referenceScope,requestScope) => request('/runs', { method: 'POST', body: { spec, runtime, ...(scenario ? { scenario } : {}), ...(referenceScope ? { reference_scope: referenceScope } : {}) },requestScope }),
  advance: (id,requestScope) => request(`/runs/${encodeURIComponent(id)}/advance`, { method: 'POST', body: {},requestScope }),
  modelStep: (id,requestScope) => request(`/runs/${encodeURIComponent(id)}/model-step`, { method: 'POST', body: {},requestScope }),
  stop: (id,requestScope) => request(`/runs/${encodeURIComponent(id)}/stop`, { method: 'POST', body: {},requestScope }),
  resume: (id,requestScope) => request(`/runs/${encodeURIComponent(id)}/resume`, { method: 'POST', body: {},requestScope }),
  submitTask: (id, taskId, version, output,requestScope) => request(`/runs/${encodeURIComponent(id)}/tasks/${encodeURIComponent(taskId)}`, { method: 'POST', body: { task_version: version, result: output },requestScope }),
  decide: (issueId, decision, note,requestScope) => request(`/reviews/${encodeURIComponent(issueId)}/decision`, { method: 'POST', body: { decision, note },requestScope }),
  goldenDemo: () => request('/golden-demo',{unscoped:true}),
  runGoldenDemo: (idempotencyKey) => request('/golden-demo',{method:'POST',body:{},unscoped:true,idempotencyKey}),
  runGoldenDemoScoped: (requestScope,idempotencyKey) => request('/demos/golden',{method:'POST',body:{},requestScope,idempotencyKey})
};
