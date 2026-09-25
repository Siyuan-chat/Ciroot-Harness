import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const app = await readFile(new URL('./app.js', import.meta.url), 'utf8');

test('executor selector switches the active conversation in place and keeps busy conflicts visible', () => {
  assert.match(app, /api\.switchConversationExecutor\(id,target,scope,executorSwitchKey\(id,target,apiConfig\),apiConfig\)/);
  assert.match(app, /function executorSwitchKey\(id,target,config\)/);
  assert.match(app, /out\.conversation\?\.conversation_id!==id/);
  assert.match(app, /RH_GUI_EXECUTOR_SWITCH_BUSY','RH_GUI_EXECUTOR_SWITCH_EXTERNAL_PENDING/);
  assert.doesNotMatch(app, /else if\(state\.conversation\.executor!==state\.chatExecutor\)\{const created=await api\.createConversation/);
  assert.match(app, /error\.code==='RH_GUI_API_CONFIG_EXPANSION'\?t\('chat\.configExpansion'/);
  assert.match(app, /state\.chatExecutor=current\.executor;state\.chatSwitchError=/);
  assert.match(app, /state\.conversation=out\.conversation;state\.chatExecutor=out\.conversation\.executor/);
});
