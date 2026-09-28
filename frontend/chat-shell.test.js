import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const app=await readFile(new URL('./app.js',import.meta.url),'utf8');
const css=await readFile(new URL('./style.css',import.meta.url),'utf8');
const i18n=await readFile(new URL('./i18n.js',import.meta.url),'utf8');
test('new workspace action stays in the top bar and Ask Agent links to the chat panel',()=>{
  assert.match(app,/<button id="create-workspace-top"/);assert.match(app,/workspace.createTop/);
  assert.match(app,/<button id="top-chat" class="quiet">/);
  assert.doesNotMatch(app,/disabled title="当前服务未提供问答接口"/);
  assert.match(app,/app\.querySelector\('#top-chat'\)[\s\S]*?mobileView='chat'[\s\S]*?app\.querySelector\('#chat-input'\)/);
});
test('chat is a right-side workspace column with narrow-window content/chat switching and optional details',()=>{
  assert.match(app,/aria-label="\$\{esc\(translate\('对象详情'/);
  assert.match(app,/\$\{chatPanel\(\)\}<\/div><details class="runbar">/);
  assert.match(css,/\.workspace\.detail-closed>\.detail\{display:none\}/);
  assert.match(app,/id="show-content"/);assert.match(app,/id="show-chat"/);
  assert.match(css,/@media\(max-width:1100px\)/);
  assert.match(css,/\.workspace\.view-content>\.chat-dock/);
  assert.match(css,/\.workspace\.view-chat>main\{display:none\}/);
  assert.match(css,/\.chat-dock\{position:relative;inset:auto/);
  assert.match(css,/\.workspace\.detail-open>\.detail\{display:block;position:absolute/);
  assert.match(css,/@media\(max-width:650px\)/);
});
test('narrow Plan view gives the assistant the full main grid without flex-shrinking its content',()=>{
  assert.match(app,/function planInvestigation\(\)[\s\S]*?state\.chatOpen=true[\s\S]*?mobileView='chat'/);
  assert.match(css,/\.workspace\.chat-open\.view-chat>\.chat-dock\{display:grid!important;grid-column:1!important;grid-row:1!important;min-height:0;width:100%;height:100%/);
  assert.doesNotMatch(css,/\.workspace\.chat-open\.view-chat>\.chat-dock\{display:flex!important/);
});
test('context and chat keep compact labels, disclosure-only low-frequency controls, and a usable composer',()=>{
  assert.match(app,/<details id="context-controls" class="context-controls">/);
  assert.match(app,/<details id="top-more" class="top-more">/);
  assert.match(app,/<select id="chat-executor" name="chat-executor"/);assert.doesNotMatch(app,/chat-context-content|范围与额度|Scope & budget/);
  assert.doesNotMatch(app,/type=\"radio\" name=\"chat-executor\"/);
  assert.match(app,/id="chat-input"[^>]*placeholder="\$\{esc\(t\('chat\.shortPlaceholder'/);
  assert.match(app,/id="chat-execute"/);
  assert.match(app,/id="chat-stop-reply"/);
  assert.match(css,/.chat-body{display:grid;grid-template-columns:minmax\(0,1fr\)/);
  assert.match(i18n,/'chat\.planConfirm':\[/);assert.match(i18n,/'chat\.executeConfirm':\[/);
});
test('CirootHarness logo, page title and native title use the approved brand',async()=>{
  const html=await (await import('node:fs/promises')).readFile(new URL('./index.html',import.meta.url),'utf8');
  const desktop=await (await import('node:fs/promises')).readFile(new URL('../src/research_harness/gui/desktop.py',import.meta.url),'utf8');
  const entry=await (await import('node:fs/promises')).readFile(new URL('../packaging/desktop_entry.py',import.meta.url),'utf8');
  assert.match(app,/src="\/assets\/ciroot-harness-logo\.png" alt="CirootHarness"/);
  assert.match(html,/<title>CirootHarness<\/title>/);assert.match(desktop,/create_window\("CirootHarness"/);
  assert.match(entry,/"CirootHarness 启动失败"/);
  assert.doesNotMatch(app,/Patent Agent|PATENT RESEARCH WORKSPACE|PATENT INSPECTOR/);
});
test('empty and unindexed libraries have distinct localized labels',()=>{
  assert.match(app,/state\.library\.length===0\?t\('library\.emptyWorkspace'/);
  assert.match(i18n,/'library\.emptyWorkspace':\[/);
  assert.match(i18n,/'library\.notIndexed':\[/);
});
test('chat history is a visible selectable rail with a separate new action and per-conversation drafts',()=>{
  assert.match(app,/class="chat-conversation-list" aria-label=/);
  assert.match(app,/id="chat-new" type="button" class="chat-new"/);
  assert.match(app,/data-conversation="\$\{esc\(x\.conversation_id\)\}" aria-current=/);
  assert.match(app,/id="chat-list-toggle"[^>]*aria-expanded="\$\{state\.chatListOpen\}"/);
  assert.match(app,/function conversationScopeKey\(scope,conversationId=state\.conversation\?\.conversation_id\|\|'draft'\)/);
  assert.match(app,/state\.chatDrafts\.get\(conversationScopeKey\(captureScope\(\),c\?\.conversation_id\|\|'draft'\)\)/);
  assert.match(app,/state\.chatDrafts\.delete\(draftKey\)/);
  assert.match(css,/\.chat-conversation-list\{grid-column:1;grid-row:1/);
  assert.match(css,/\.workspace\.chat-closed/);
});
test('workspace creation dialog uses aligned full-width fields, compact optional text, accessible focus and responsive actions',()=>{
  assert.match(app,/dialog\.className='workspace-dialog'/);
  assert.match(app,/aria-labelledby="workspace-dialog-title"/);
  assert.match(app,/name="name" maxlength="80" required autofocus/);
  assert.match(app,/textarea name="description" rows="3" maxlength="500"/);
  assert.match(app,/data-empty-library-note/);
  assert.match(app,/workspace-dialog-actions/);
  assert.match(css,/\.workspace-dialog\{width:min\(34rem,calc\(100vw - 2rem\)\)/);
  assert.match(css,/\.workspace-field\{display:grid;gap:/);
  assert.match(css,/\.workspace-field textarea\{height:auto;min-height:5rem/);
  assert.match(css,/@media\(max-width:480px\)\{\.workspace-dialog/);
});
test('details drawer overlays content so it does not narrow the document list beside chat',()=>{
  assert.match(css,/\.workspace>\.detail,\.workspace\.detail-open>\.detail\{display:block;position:absolute/);
  assert.match(css,/right:max\(390px,31vw\)/);
  assert.match(css,/\.workspace\.detail-closed>\.detail\{display:none\}/);
  assert.match(css,/min-width:min\(300px,calc\(100vw - 148px\)\)/);
});
test('selecting workspace, library, collection, or the library nav returns to the scoped library content view',()=>{
  assert.match(app,/state\.page='library';mobileView='content';setScope\(/);
  assert.match(app,/await loadLibrary\(generation\);await syncEvents/);
  assert.match(app,/if\(page==='library'\)mobileView='content'/);
  assert.match(app,/app\.querySelectorAll\('\[data-page\]'\)\.forEach\(b=>b\.onclick=\(\)=>\{mobileNavOpen=false;loadPage\(b\.dataset\.page\)\}\)/);
  assert.match(app,/state\.loading&&state\.libraryStatus==null[\s\S]*?正在读取所选文献库/);
});
