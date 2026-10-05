import test from 'node:test';
import assert from 'node:assert/strict';
import {t} from './i18n.js';
import {renderGoldenDemoCard} from './components/golden-demo-card.js';
import {renderStatusBadge} from './components/status-badge.js';

test('Golden Demo card labels the canonical run and shares its CTA hook',()=>{
  const html=renderGoldenDemoCard({t,locale:'ja'});
  assert.match(html,/オフライン/);assert.match(html,/合成/);assert.match(html,/API キー不要/);
  assert.match(html,/data-golden-demo/);
  assert.match(renderGoldenDemoCard({t,locale:'zh',starting:true}),/disabled/);
});

test('status badges distinguish partial from failed and escape unknown backend states',()=>{
  const partial=renderStatusBadge('partial',t,'en');
  const failed=renderStatusBadge('failed',t,'en');
  assert.match(partial,/status-partial/);assert.match(partial,/Partial/);
  assert.match(failed,/status-failed/);assert.match(failed,/Failed/);
  assert.match(renderStatusBadge('<unknown>',t,'en'),/&lt;unknown&gt;/);
});
