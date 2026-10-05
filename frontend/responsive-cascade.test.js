import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const css=await readFile(new URL('./style.css',import.meta.url),'utf8');

function rulesAt(cssText,width){
  const rules=[];
  function parse(text){
    let cursor=0;
    while(cursor<text.length){
      const open=text.indexOf('{',cursor);
      if(open<0)break;
      const prelude=text.slice(cursor,open).trim();
      let depth=1,end=open+1;
      while(end<text.length&&depth){if(text[end]==='{')depth++;else if(text[end]==='}')depth--;end++}
      const body=text.slice(open+1,end-1);
      cursor=end;
      if(prelude.startsWith('@media')){
        const min=Number(prelude.match(/min-width\s*:\s*(\d+)px/)?.[1]||0);
        const max=Number(prelude.match(/max-width\s*:\s*(\d+)px/)?.[1]||Infinity);
        if(width>=min&&width<=max)parse(body);
      }else if(!prelude.startsWith('@')){
        const declarations=Object.fromEntries(body.split(';').map(item=>item.trim()).filter(Boolean).map(item=>{const split=item.indexOf(':');return [item.slice(0,split).trim(),item.slice(split+1).trim()]}));
        for(const selector of prelude.split(','))rules.push({selector:selector.trim(),declarations});
      }
    }
  }
  parse(cssText);
  return rules;
}

  function winningDeclaration(rules,classes,property,element='workspace'){
  const candidates=[];
  for(let order=0;order<rules.length;order++){
    const {selector,declarations}=rules[order];
    if(!(property in declarations))continue;
    if(element==='sidebar'&&!selector.includes('.sidebar'))continue;
    if(element==='detail'&&!selector.includes('.detail'))continue;
    const workspace=selector.match(/\.workspace((?:\.[\w-]+)*)/);
    if(!workspace&&element!=='detail')continue;
    const required=workspace?['workspace',...(workspace[1].match(/[\w-]+/g)||[])]:[];
    if(required.some(name=>!classes.has(name)))continue;
    const value=declarations[property];
    candidates.push({value:value.replace(/\s*!important\s*$/,''),important:/!important\s*$/.test(value),specificity:(selector.match(/\.[\w-]+/g)||[]).length,order});
  }
  candidates.sort((a,b)=>Number(a.important)-Number(b.important)||a.specificity-b.specificity||a.order-b.order);
  return candidates.at(-1)?.value;
}

test('390px workspace grid cascade resolves to one full-width main column in content and assistant states',()=>{
  const rules=rulesAt(css,390);
  const states=[
    ['workspace','page-overview','view-content','detail-closed','chat-closed'],
    ['workspace','page-overview','view-content','detail-open','chat-closed'],
    ['workspace','page-overview','view-chat','detail-closed','chat-open'],
    ['workspace','page-overview','view-chat','detail-open','chat-open'],
  ];
  for(const state of states){
    const columns=winningDeclaration(rules,new Set(state),'grid-template-columns');
    assert.equal(columns,'minmax(0,1fr)',`${state.join(' ')} must have one mobile column`);
  }
  assert.equal(winningDeclaration(rules,new Set(states[0]),'display','sidebar'),'none','default sidebar must be hidden');
  assert.equal(winningDeclaration(rules,new Set([...states[0],'nav-open']),'display','sidebar'),'block','expanded sidebar must be available');
});

test('390px open Evidence Inspector beats legacy important hide rule in the computed cascade',()=>{
  const rules=rulesAt(css,390);
  const openInspector=new Set(['workspace','page-overview','view-content','detail-open','inspector-open','chat-closed']);
  assert.equal(winningDeclaration(rules,openInspector,'display','detail'),'block','open inspector must render despite the legacy mobile display:none!important rule');
});

test('closed Assistant does not reserve a desktop column at supported widths',()=>{
  for(const width of [1440,1280,1024]){
    const rules=rulesAt(css,width);
    const classes=new Set(['workspace','page-overview','view-content','detail-closed','chat-closed']);
    const columns=winningDeclaration(rules,classes,'grid-template-columns');
    assert.equal(columns,width<=1100?'148px minmax(0,1fr)':'196px minmax(0,1fr)',`${width}px should give the closed Assistant no grid track`);
    assert.equal(winningDeclaration(rules,classes,'display','detail'),'none');
  }
});

test('status semantics remain distinct and report content keeps a readable measure',()=>{
  const rules=rulesAt(css,1440);
  const declarations=selector=>rules.find(rule=>rule.selector===selector)?.declarations||{};
  assert.equal(declarations('.status-partial').background,'var(--status-partial-bg)');
  assert.equal(declarations('.status-failed').background,'var(--status-failed-bg)');
  assert.notEqual(declarations('.status-partial').background,declarations('.status-failed').background);
  assert.match(css,/--status-partial-bg:#fff4db/);
  assert.match(css,/--status-failed-bg:#feeeee/);
  assert.match(css,/\.report-reader\{width:min\(100%,820px\);margin-inline:auto\}/);
  assert.match(css,/\.report-section\{[^}]*overflow-wrap:anywhere/);
});

test('Escape returns focus to the visible Assistant and History controls expose expansion state',async()=>{
  const app=await readFile(new URL('./app.js',import.meta.url),'utf8');
  assert.match(app,/function focusAssistantOpener\(\)[^{]*\{const opener=\[app\.querySelector\('#top-chat'\),app\.querySelector\('#show-chat'\)\]/);
  assert.match(app,/if\(state\.chatListOpen\)\{state\.chatListOpen=false;render\(\);app\.querySelector\('#chat-list-toggle'\)\?\.focus/);
  assert.match(app,/id="chat-list-toggle"[^>]*aria-expanded="\$\{state\.chatListOpen\}"/);
});
