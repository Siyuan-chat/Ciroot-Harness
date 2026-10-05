import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const css = await readFile(new URL('./style.css', import.meta.url), 'utf8');

function rulesIn(source, width, rules = []) {
  let i = 0;
  while (i < source.length) {
    const open = source.indexOf('{', i);
    if (open < 0) break;
    const selector = source.slice(i, open).trim();
    let depth = 1, close = open + 1;
    while (close < source.length && depth) {
      if (source[close] === '{') depth++;
      else if (source[close] === '}') depth--;
      close++;
    }
    const body = source.slice(open + 1, close - 1);
    if (selector.startsWith('@media')) {
      const max = selector.match(/max-width\s*:\s*(\d+)px/);
      const min = selector.match(/min-width\s*:\s*(\d+)px/);
      const active = (!max || width <= Number(max[1])) && (!min || width >= Number(min[1]));
      if (active) rulesIn(body, width, rules);
    } else if (selector) rules.push({ selector, body, order: rules.length });
    i = close;
  }
  return rules;
}

function computedWorkspaceValue(classNames, property, width) {
  const classes = new Set(classNames.split(/\s+/));
  let winner = null;
  for (const rule of rulesIn(css.replace(/\/\*[\s\S]*?\*\//g, ''), width)) {
    const declaration = rule.body.split(';').map(x => x.trim()).find(x => x.startsWith(`${property}:`));
    if (!declaration) continue;
    for (const selector of rule.selector.split(',')) {
      const normalized = selector.trim();
      if (!normalized.startsWith('.workspace') || /[ >:+~\[]/.test(normalized)) continue;
      const required = [...normalized.matchAll(/\.([\w-]+)/g)].map(m => m[1]);
      if (!required.every(name => classes.has(name))) continue;
      const important = /!important\s*$/.test(declaration);
      const specificity = required.length;
      if (!winner || Number(important) > Number(winner.important) ||
          (important === winner.important && specificity > winner.specificity) ||
          (important === winner.important && specificity === winner.specificity && rule.order >= winner.order)) {
        winner = { value: declaration.slice(declaration.indexOf(':') + 1).replace(/!important/, '').trim(), important, specificity, order: rule.order };
      }
    }
  }
  return winner?.value;
}

test('mobile workspace grid resolves to one full-width column across chat and inspector states', () => {
  const states = [
    'workspace detail-closed chat-closed view-content',
    'workspace detail-open chat-closed view-content',
    'workspace detail-closed chat-open view-chat',
    'workspace detail-open chat-open view-chat',
  ];
  for (const state of states) assert.equal(computedWorkspaceValue(state, 'grid-template-columns', 390), 'minmax(0,1fr)', state);
  assert.match(css, /\.workspace\.nav-open>\.sidebar\{display:block!important/);
  assert.match(css, /\.workspace\.chat-open\.view-chat>\.chat-dock\{display:grid!important/);
  assert.equal(computedWorkspaceValue('workspace detail-closed chat-closed view-content', 'grid-template-columns', 1024), '148px minmax(0,1fr)');
  for (const width of [1280, 1440]) {
    assert.equal(computedWorkspaceValue('workspace detail-closed chat-closed view-content', 'grid-template-columns', width), '220px minmax(0,1fr) 0');
  }
});

test('visual tokens keep partial, failed, success, active and unknown states distinct', () => {
  assert.match(css, /--status-partial:[^;]+;--status-partial-bg:[^;]+;/);
  assert.match(css, /--status-failed:[^;]+;--status-failed-bg:[^;]+;/);
  assert.match(css, /\.badge\.partial,\.status-partial[^{]+\{color:var\(--status-partial\)/);
  assert.match(css, /\.badge\.failed,\.status-failed\{color:var\(--status-failed\)/);
  assert.match(css, /\.status-badge\[class\*="unknown"\],\.status-unknown/);
  assert.match(css, /\.badge\.synthetic\{color:var\(--brand-teal-dark\);background:var\(--brand-tint\)/);
  assert.match(css, /--status-review:[^;]+;--status-review-bg:[^;]+;/);
  assert.match(css, /\.status-needs_review,\.status-open\{color:var\(--status-review\)/);
});

test('focus, active navigation and long identifiers have visible, resilient styles', () => {
  assert.match(css, /:focus-visible\{outline:3px solid var\(--brand-teal\);outline-offset:2px/);
  assert.match(css, /\.sidebar button\[aria-current=page\]/);
  assert.match(css, /\.workspace code,\.workspace dd,\.workspace \.page-status[^{]*\{[^}]*overflow-wrap:anywhere/);
});
