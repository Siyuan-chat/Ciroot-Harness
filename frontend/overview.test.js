import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {t} from './i18n.js';
import {renderOverview} from './pages/overview.js';

const app=await readFile(new URL('./app.js',import.meta.url),'utf8');

test('Overview is the default route with four primary destinations and separate Settings',()=>{
  assert.match(app,/page: 'overview'/);
  assert.match(app,/const nav = \[\['overview','nav\.overview'\],\['library','nav\.library'\],\['investigations','nav\.investigations'\],\['reports','nav\.reportsReview'\],\['settings','nav\.settings'\]\]/);
  assert.match(app,/nav\.slice\(0,4\)/);
  assert.match(app,/class="nav-settings" data-page="settings"/);
  assert.doesNotMatch(app,/\['reader','|\['patents','/);
});

test('Overview renders offline demo labels and leaves unknown counts unknown',()=>{
  const html=renderOverview({overview:{workspace:{name:'Polymer'},library:{index_status:'unindexed',document_count:null},recent_runs:[{run_id:'inv-1',project_id:'study',outcome:'partial',research_question:'Question',verified_claim_count:null,open_issue_count:null}],review_summary:{open_run_issue_count:null}},locale:'en',questionDraft:'',t});
  assert.match(html,/OFFLINE/);assert.match(html,/SYNTHETIC/);assert.match(html,/NO API KEY/);
  assert.match(html,/Unknown documents/);assert.match(html,/Unknown verified claims/);assert.match(html,/Unknown open issues/);
  assert.doesNotMatch(html,/0 documents|0 verified claims|0 open issues/);
  assert.match(html,/data-golden-demo/);assert.match(html,/data-open-overview-run="inv-1"/);
});

test('Plan Investigation stores the scoped draft and opens the assistant without sending',()=>{
  const plan=app.match(/function planInvestigation\(\)\{([\s\S]*?)\}\nasync function openOverviewRun/)?.[1]||'';
  assert.match(plan,/conversationScopeKey\(scope,state\.conversation\?\.conversation_id\|\|'draft'\)/);
  assert.match(plan,/state\.chatDrafts\.set\(draftKey,question\)/);
  assert.match(plan,/state\.chatOpen=true/);
  assert.doesNotMatch(plan,/api\.|conversationTurn|executeConversation/);
  assert.match(app,/chatOpen:false/);
});

test('Golden Demo uses one handler for Overview and empty-state CTAs, then opens only the returned run',()=>{
  assert.match(app,/app\.querySelectorAll\('\[data-golden-demo\]'\)\.forEach\(button=>button\.addEventListener\('click',startGoldenDemo\)\)/);
  assert.match(app,/api\.goldenDemo\(scope,key\)/);
  assert.match(app,/api\.run\(created\.run_id,scope\)/);
  assert.match(app,/state\.page='investigations'/);
  assert.match(app,/demoIdempotencyKey=crypto\.randomUUID\(\)/);
});

test('assistant History is a disclosure popover and executor settings are under Advanced',()=>{
  assert.match(app,/id="chat-list-toggle"[^>]*aria-expanded="\$\{state\.chatListOpen\}"/);
  assert.match(app,/class="chat-conversation-list" aria-label=/);
  assert.match(app,/class="chat-advanced"><summary>\$\{esc\(t\('assistant\.advanced'/);
  assert.match(app,/class="chat-executor-label"/);
});
