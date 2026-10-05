import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app=await readFile(new URL('./app.js',import.meta.url),'utf8');

test('Main to Assistant opens the full panel in one action and preserves the scoped draft',()=>{
  assert.match(app,/app\.querySelector\('#show-chat'\)\?\.addEventListener\('click',showMobileAssistant\)/);
  const functionSource=app.match(/function showMobileAssistant\(\)\{[^\n]+/)?.[0];
  const contentFunction=app.match(/function showMobileContent\(\)\{[^\n]+/)?.[0];
  assert.ok(functionSource,'shared assistant open handler must exist');
  assert.ok(contentFunction,'content switch handler must exist');
  assert.match(app,/app\.querySelector\('#show-content'\)\?\.addEventListener\('click',showMobileContent\)/);
  const execute=new Function('state','app','focusProbe',`let mobileView='content';let rendered=null;function render(){rendered={chatOpen:state.chatOpen,mobileView}};${functionSource};${contentFunction};showMobileAssistant();const opened={...rendered,mobileView};showMobileContent();return {state,mobileView,opened,rendered,focused:focusProbe.focused}`);
  const draft=new Map([['workspace:library:collection:draft','draft text']]);
  const state={chatOpen:false,chatListOpen:true,chatDrafts:draft,conversation:{conversation_id:'conversation-1'}};
  const focusProbe={focused:false};
  const result=execute(state,{querySelector(selector){assert.equal(selector,'#chat-input');return {focus(){focusProbe.focused=true}}}},focusProbe);
  assert.equal(result.state.chatOpen,true);
  assert.equal(result.state.chatListOpen,false);
  assert.equal(result.opened.mobileView,'chat');
  assert.equal(result.mobileView,'content');
  assert.deepEqual(result.opened,{chatOpen:true,mobileView:'chat'});
  assert.deepEqual(result.rendered,{chatOpen:true,mobileView:'content'});
  assert.equal(result.state.chatDrafts,draft);
  assert.equal(result.state.chatDrafts.get('workspace:library:collection:draft'),'draft text');
  assert.equal(result.state.conversation.conversation_id,'conversation-1');
  assert.equal(result.focused,true);
});
