import test from 'node:test';
import assert from 'node:assert/strict';
import { conversationCreateBody, conversationExecutionBody } from './api.js';

test('API conversation creation binds the user supplied config without fixture scope', () => {
  const config = {provider:'openai',model:'offline-fake',max_planning_calls:2,max_output_tokens:1000,timeout_seconds:30,total_model_calls:5,runtime_template:{mode:'api',data_mode:'synthetic',allow_network:true,model_api:{provider:'openai',model:'offline-fake',api_key_env:'OPENAI_API_KEY',max_output_tokens:1000,timeout_seconds:30},budget:{max_model_calls:5}}};
  assert.deepEqual(conversationCreateBody('api',config),{executor:'api',api_config:config});
  assert.deepEqual(conversationCreateBody('scripted',config),{executor:'scripted',fixture_id:'synthetic-d19'});
});

test('API execution has explicit confirmation and synthetic scenario; scripted keeps its fixture contract', () => {
  const scenario = {scenario_id:'synthetic-fake'};
  assert.deepEqual(conversationExecutionBody('api',scenario),{scenario,confirm_api_execution:true});
  assert.deepEqual(conversationExecutionBody('scripted',scenario),{});
});
