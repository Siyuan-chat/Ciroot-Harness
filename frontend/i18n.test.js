import test from 'node:test';
import assert from 'node:assert/strict';
import { translate, t, resolveLocale } from './i18n.js';

test('interface labels support Chinese, English and Japanese without rewriting source titles', () => {
  assert.equal(translate('文献库', 'zh'), '文献库');
  assert.equal(translate('文献库', 'en'), 'Literature library');
  assert.equal(translate('文献库', 'ja'), '文献ライブラリ');
  assert.equal(translate('A Brief Review of Anion Exchange Membranes', 'ja'), 'A Brief Review of Anion Exchange Membranes');
});

test('stable dynamic messages translate named parameters without translating identifiers', () => {
  assert.equal(t('run.summary',{stage:'analysis',status:'partial',coverage:'partial'},'en'),'analysis · partial · Coverage partial');
  assert.equal(t('count.loaded',{matches:2,loaded:5},'ja'),'2 件一致 / 5 件読み込み済み');
  assert.equal(t('error.request',{code:'RH_UNKNOWN_X',message:t('error.generic',{},'en')},'en').startsWith('RH_UNKNOWN_X:'),true);
});

test('workspace creation prompts are available in all supported interface languages',()=>{
  assert.equal(t('workspace.create',{},'zh'),'新建工作区');
  assert.equal(t('workspace.createAndEnter',{},'en'),'Create and enter');
  assert.equal(t('workspace.emptyUnindexed',{},'ja'),'新しい空の文献ライブラリは未索引状態で作成されます。');
});
test('reader evidence label and the always-visible session rail have English and Japanese copy',()=>{
  assert.equal(translate('证据 ID','en'),'Evidence ID');
  assert.equal(translate('证据 ID','ja'),'証拠 ID');
  assert.equal(t('chat.sessions',{},'en'),'Chats');
  assert.equal(t('chat.new',{},'ja'),'新しい会話');
  assert.equal(t('chat.collapseSessions',{},'en'),'Collapse chat list');
  assert.equal(t('workspace.emptyUnindexed',{},'en'),'A new empty literature library starts unindexed.');
});
test('saved language takes precedence; first launch follows Chinese or Japanese browser language and otherwise English',()=>{
  assert.equal(resolveLocale('ja',['zh-CN']),'ja');
  assert.equal(resolveLocale('', ['zh-CN','en-US']),'zh');
  assert.equal(resolveLocale(null,['ja-JP']),'ja');
  assert.equal(resolveLocale(null,['fr-FR']),'en');
});
test('chat labels distinguish offline synthetic execution from controlled API planning',()=>{
  assert.equal(t('chat.synthetic','zh'),'合成演示 · synthetic-d19');
  assert.equal(t('chat.planningPending',{},'en'),'Text starts controlled API planning. Execution is unavailable until a valid ResearchSpec is ready.');
  assert.equal(t('chat.stopInvestigation',{},'ja'),'調査を停止');
});
test('executor switching explains same-conversation action and busy conflicts in three languages',()=>{
  assert.match(t('chat.switchAction',{},'zh'),/当前会话/);
  assert.match(t('chat.switchAction',{},'en'),/this conversation/);
  assert.match(t('chat.switchAction',{},'ja'),/現在の会話/);
  assert.match(t('chat.switchBusy',{},'zh'),/执行器未切换/);
  assert.match(t('chat.switchBusy',{},'en'),/executor was not changed/);
  assert.match(t('chat.switchBusy',{},'ja'),/実行器は変更されません/);
  assert.match(t('chat.configExpansion',{},'zh'),/扩大了此前会话/);
  assert.match(t('chat.configExpansion',{},'en'),/expands this conversation/);
  assert.match(t('chat.configExpansion',{},'ja'),/拡張しています/);
});
