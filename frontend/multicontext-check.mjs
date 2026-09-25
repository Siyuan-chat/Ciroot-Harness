import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
const {chromium}=await import(pathToFileURL(resolve(process.env.PLAYWRIGHT_MODULE)).href);
const root=resolve('frontend/dist');const output=resolve(process.env.MULTICONTEXT_OUTPUT_DIR||'.local/gui-layout-acceptance/f04-scope-fix-20260925');await mkdir(output,{recursive:true});
const ws=[{workspace_id:'w1',name:'Workspace A',default_library_id:'l1',libraries:[{library_id:'l1',name:'Library A',collections:[{collection_id:'all',name:'All documents'},{collection_id:'c1',name:'Group A'}]},{library_id:'l2',name:'Library B',collections:[{collection_id:'all',name:'All documents'}]}]},{workspace_id:'w2',name:'Workspace B',default_library_id:'l3',libraries:[{library_id:'l3',name:'Library C',collections:[{collection_id:'all',name:'All documents'}]}]}];
const run={run_id:'fixture-run',stage:'analysis',status:'running',synthetic:true,coverage:{complete:false,queries:[]},budget:{max_tasks:1},waiting_reason:'fixture'};
const runs=[run,{...run,run_id:'run-a',stage:'source',waiting_reason:'stale-A'},{...run,run_id:'run-b',stage:'analysis',waiting_reason:'current-B'}];
const conversations=[{conversation_id:'chat-a',library_id:'l1',collection_id:'all',executor:'scripted',status:'awaiting_input',created_at:1780000000},{conversation_id:'chat-b',library_id:'l1',collection_id:'all',executor:'scripted',status:'awaiting_input',created_at:1780000100}];
const contextRequests=[],libraryRequests=[];
const server=createServer(async(req,res)=>{
 const u=new URL(req.url,'http://x'),p=u.pathname;let d={schema_version:'1'};
 if(p==='/api/v1/registry')d={schema_version:'1',workspaces:ws};
 else if(p==='/api/v1/contexts'){const wid=req.headers['x-workspace-id']||'w1',lid=req.headers['x-library-id']||'l1',cid=req.headers['x-collection-id']||'all';contextRequests.push({workspace:wid,library:lid,collection:cid});const w=ws.find(x=>x.workspace_id===wid),l=w?.libraries.find(x=>x.library_id===lid);d={...d,workspace_id:wid,library_id:lid,collection_id:cid,workspaces:ws.map(x=>({workspace_id:x.workspace_id,name:x.name})),libraries:w?.libraries.map(x=>({library_id:x.library_id,name:x.name,read_only:true,index_status:'ready',default:x.library_id===w.default_library_id}))||[],collections:l?.collections.map(x=>({...x,member_count:0}))||[],cross_library_search:false}}
 else if(p==='/api/v1/capabilities')d={...d,capabilities:{events:true,advance:true,stop:false,resume:false}};
 else if(p==='/api/v1/conversations')d={...d,items:conversations};
 else if(/^\/api\/v1\/conversations\/chat-[ab]$/.test(p)){const id=p.endsWith('chat-a')?'chat-a':'chat-b',summary=conversations.find(x=>x.conversation_id===id);d={...d,conversation:{...summary,messages:[{role:'user',content:id==='chat-a'?'First synthetic conversation':'Second synthetic conversation',refs:{}}],tool_results:[]}}}
 else if(p==='/api/v1/library'){const wid=req.headers['x-workspace-id']||'w1',lid=req.headers['x-library-id']||'l1',cid=req.headers['x-collection-id']||'all',cursor=u.searchParams.get('cursor');libraryRequests.push({workspace:wid,library:lid,collection:cid,cursor});if(cursor==='next'){if(lid==='l1')await new Promise(r=>setTimeout(r,400));d={...d,items:[{document_id:'late-doc',title:lid==='l1'?'late A row':'late B row',document_type:'paper'}],index_status:'ready',total:2}}else d={...d,items:[{document_id:'same-doc',title:lid==='l1'?(cid==='c1'?'Group A title':'分析'):'B only title',document_type:'paper'}],index_status:'ready',total:1,next_cursor:lid==='l1'?'next':null}}
 else if(p==='/api/v1/runs')d={...d,items:runs};else if(p==='/api/v1/runs/fixture-run')d={...d,...run};else if(p==='/api/v1/runs/fixture-run/tasks')d={...d,items:[]};
 else if(/^\/api\/v1\/runs\/(run-a|run-b)$/.test(p))d={...d,...runs.find(x=>p.endsWith(x.run_id))};else if(/^\/api\/v1\/runs\/(run-a|run-b)\/tasks$/.test(p))d={...d,items:[]};
 else if(/^\/api\/v1\/runs\/fixture-run\/events$/.test(p))d={...d,snapshot:run,events:[],next_seq:0,transport:'poll'}
 else if(/^\/api\/v1\/runs\/(run-a|run-b)\/events$/.test(p)){const id=p.includes('run-a')?'run-a':'run-b';if(id==='run-a')await new Promise(r=>setTimeout(r,900));d={...d,snapshot:runs.find(x=>x.run_id===id),events:[],next_seq:0,transport:'poll'}}
 else if(p==='/api/v1/model-credentials')d={...d,providers:{}};else if(p==='/api/v1/source-credentials')d={...d,sources:{}};else if(p==='/api/v1/mcp-setup')d={...d,python_ready:false};
 if(p==='/api/v1/runs/fixture-run/advance'&&req.method==='POST')await new Promise(r=>setTimeout(r,350));
 res.setHeader('content-type','application/json');if(p.startsWith('/api/v1/')){res.end(JSON.stringify(d));return}
 try{let f=p==='/'?'index.html':p.slice(1);res.setHeader('content-type',f.endsWith('.js')?'text/javascript':f.endsWith('.css')?'text/css':f.endsWith('.json')?'application/json':'text/html');res.end(await readFile(join(root,f)))}catch{res.statusCode=404;res.end('Not found')}
});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
let browser;const failures=[],rows=[];
try{
 browser=await chromium.launch({headless:true,executablePath:process.env.EDGE_EXECUTABLE});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 const setLocale=async locale=>{if(!await page.locator('#top-more').evaluate(el=>el.open))await page.locator('#top-more summary').click();await page.locator('#language-select').selectOption(locale);await page.locator('#top-more summary').click()};
 const selectContext=async(selector,value)=>{if(!await page.locator(selector).isVisible())await page.locator('#context-controls summary').click();await page.locator(selector).selectOption(value)};
 page.on('pageerror',e=>failures.push('pageerror '+e.message));
 page.on('response',r=>{if(r.url().includes('/api/v1/runs'))console.log('API',r.status(),new URL(r.url()).pathname)});
 await page.addInitScript(()=>{localStorage.setItem('rh-workspace','w1');localStorage.setItem('rh-library','l1');localStorage.setItem('rh-collection','all')});
 await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
 await page.goto(`http://127.0.0.1:${server.address().port}`);await page.locator('#top-more summary').click();await page.waitForFunction(()=>document.querySelector('#top-more')?.open);await page.waitForSelector('#context-controls summary');await page.locator('#context-controls summary').click();await page.waitForSelector('#context-library');await page.locator('h3[data-source-content="true"]').first().waitFor();
 for(const locale of ['en','ja']){await setLocale(locale);if(await page.locator('h3[data-source-content="true"]').first().textContent()!=='分析')failures.push(`source title translated in ${locale}`)}
 await page.locator('.chat-conversation-list').waitFor();await page.locator('[data-conversation="chat-a"]').waitFor();
 await page.locator('#chat-input').fill('Draft kept with first conversation');await page.locator('[data-conversation="chat-b"]').click();await page.waitForFunction(()=>document.querySelector('#chat-input')?.value==='');await page.locator('[data-conversation="chat-a"]').click();await page.waitForFunction(()=>document.querySelector('#chat-input')?.value==='Draft kept with first conversation');
 await page.locator('#chat-list-toggle').click();if(await page.locator('.chat-conversation-list').isVisible())failures.push('session rail did not collapse');await page.locator('#chat-list-toggle').click();if(!await page.locator('.chat-conversation-list').isVisible())failures.push('session rail did not reopen');
 await page.locator('#chat-toggle').click();if(!await page.locator('#chat-panel').evaluate(el=>el.classList.contains('closed')))failures.push('chat side panel did not collapse');await page.locator('#top-chat').click();await page.locator('#chat-panel:not(.closed)').waitFor();
 await page.locator('[data-page="reader"]').click();await setLocale('en');await page.waitForSelector('#reader-evidence-id');if(await page.locator('.toolbar').textContent()&&!((await page.locator('.toolbar').textContent()).includes('Evidence ID')))failures.push('U01 reader label remained untranslated');await page.locator('[data-page="library"]').click();await page.locator('h3[data-source-content="true"]').first().waitFor();
 for(const locale of ['en','ja']){await setLocale(locale);if(await page.locator('h3[data-source-content="true"]').first().textContent()!=='分析')failures.push(`source title translated in ${locale}`)}
 for(const [width,height] of [[1440,900],[1280,800],[1024,768],[850,600],[750,700],[390,844]]){
  await page.setViewportSize({width,height});if(width<=1100&&await page.locator('#show-content').isVisible())await page.locator('#show-content').click();
  for(const locale of ['zh','en','ja']){
   await setLocale(locale);
   const m=await page.evaluate(()=>({width:innerWidth,doc:document.documentElement.scrollWidth,footer:document.querySelector('.runbar').getBoundingClientRect().toJSON()}));
   const g=await page.evaluate(()=>{const box=s=>{const e=document.querySelector(s);if(!e||getComputedStyle(e).display==='none')return null;const r=e.getBoundingClientRect();return {x:r.x,width:r.width,right:r.right}};return {main:box('main'),chat:box('.chat-dock'),detail:box('.detail'),body:document.body.scrollWidth,view:document.querySelector('.workspace').className}});rows.push({width,height,locale,...m,geometry:g});
   if(m.doc>width+2||g.body>width+2)failures.push(`horizontal overflow ${width}/${locale}: ${g.body}/${m.doc}`);
   if(width>=850&&(m.footer.bottom>height+1))failures.push(`footer outside view ${width}/${locale}`);
   if(width===850||width===750||width===1280||width===1440){await page.evaluate(()=>{for(const id of ['context-controls','top-more']){const d=document.querySelector(`#${id}`);if(d)d.open=false}});await page.screenshot({path:join(output,`${locale}-${width}x${height}.png`)});}
  }
  if(width<=1100||width===1280){if(width<=1100)await page.locator('#show-chat').click();await page.locator('.chat-conversation-list').waitFor();const cg=await page.evaluate(()=>({body:document.body.scrollWidth,doc:document.documentElement.scrollWidth,chat:document.querySelector('.chat-dock').getBoundingClientRect().toJSON(),message:document.querySelector('.chat-messages').getBoundingClientRect().toJSON(),rail:document.querySelector('.chat-conversation-list').getBoundingClientRect().toJSON()}));rows.push({kind:'chat-layout',width,height,...cg});if(cg.body>width+2||cg.doc>width+2||cg.message.width<150)failures.push(`chat layout ${width}: ${JSON.stringify(cg)}`);if(width<=1100&&(cg.chat.x>1||cg.chat.width<width-2))failures.push(`chat view retained a side navigation column ${width}: ${JSON.stringify(cg.chat)}`);if(width>=1200&&(cg.rail.width<180||cg.rail.width>220))failures.push(`wide session rail width ${width}: ${JSON.stringify(cg.rail)}`);if(width===850||width===750||width===390||width===1280)await page.screenshot({path:join(output,`chat-${width}x${height}.png`)});if(width<=1100)await page.locator('#show-content').click()}
 }
 await page.setViewportSize({width:850,height:600});
 for(const zoom of [1.25,1.5]){
  await page.evaluate(z=>document.documentElement.style.fontSize=`${16*z}px`,zoom);
  const m=await page.evaluate(()=>({zoom:getComputedStyle(document.documentElement).fontSize,width:innerWidth,height:innerHeight,doc:document.documentElement.scrollWidth,body:document.body.scrollWidth,footer:document.querySelector('.runbar').getBoundingClientRect().bottom}));rows.push({kind:'font-zoom',...m});
  if(m.doc>m.width+2||m.body>m.width+2||m.footer>m.height+1)failures.push(`font zoom ${zoom} ${JSON.stringify(m)}`);
  await page.screenshot({path:join(output,`font-${Math.round(zoom*100)}.png`)});
  await page.evaluate(()=>document.documentElement.style.fontSize='');
 }
 await page.click('[data-page="runs"]');await page.locator('main details').first().locator('summary').first().click();await page.waitForSelector('#research-question');
 await page.locator('#research-question').fill('U02 retained research draft');
 await page.locator('#research-question').focus();
 for(const locale of ['en','ja','zh'])await setLocale(locale);
 if(await page.locator('#research-question').inputValue()!=='U02 retained research draft')failures.push('research draft lost on locale change');
 if(!await page.locator('main details').first().evaluate(el=>el.open))failures.push('details disclosure lost on locale change');
 await page.locator('[data-select="run:0"]').click();await page.waitForTimeout(300);await setLocale('en');
 if(await page.locator('#advance').count()){const advanceClick=page.locator('#advance').click();await page.locator('.write-waiting').first().waitFor();await advanceClick;await page.locator('.write-waiting').first().waitFor({state:'detached'})}else failures.push('fixture run did not load for U01/U09');
 const untranslated=await page.evaluate(()=>{const out=[],walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);for(let n=walker.nextNode();n;n=walker.nextNode()){const p=n.parentElement;if(!p?.getClientRects().length||p.closest('pre,textarea,script,style,option,[data-source-content],[data-report-content],[data-user-content],[data-technical-content]'))continue;if(/[\u3400-\u9fff]/.test(n.textContent.trim()))out.push(n.textContent.trim())}return [...new Set(out)]});
 rows.push({kind:'dynamic-english-copy',untranslated});if(untranslated.length)failures.push(`U01 untranslated: ${untranslated.join(' | ')}`);
 const waitAResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/runs/run-a/events'&&r.status()===200);await page.locator('[data-select="run:1"]').click();
 const waitBResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/runs/run-b/events'&&r.status()===200);await page.locator('[data-select="run:2"]').click();await waitBResponse;
 await page.waitForFunction(()=>document.querySelector('.page-status')?.textContent?.includes('run-b'));
 await waitAResponse;
 const u08=await page.evaluate(()=>({pageStatus:document.querySelector('.page-status')?.textContent?.trim(),route:document.querySelector('.runbar-meta')?.textContent?.trim(),runbar:document.querySelector('.runbar summary')?.textContent?.trim(),selectedB:document.querySelector('[data-select="run:2"]')?.getAttribute('aria-pressed')}));
 rows.push({kind:'U08-late-run-response',...u08});
 if(!u08.pageStatus?.includes('run-b')||!u08.route?.includes('run-b')||!u08.route?.includes('current-B')||!u08.runbar?.includes('analysis'))failures.push(`U08 stale response changed current task/route/status: ${JSON.stringify(u08)}`);
 await page.click('[data-page="settings"]');await page.waitForTimeout(100);
 const secretInput=page.locator('input[type="password"]').first();
 if(await secretInput.count()){await secretInput.fill('fixture-secret-should-not-persist');await setLocale('en');if(await page.locator('input[type="password"]').first().inputValue()!=='fixture-secret-should-not-persist')failures.push('in-memory secret lost on locale change')}
 if(await page.evaluate(()=>JSON.stringify(localStorage).includes('fixture-secret-should-not-persist')))failures.push('secret value persisted');
 await page.click('[data-page="library"]');await page.waitForSelector('#more');
 const lateMore=page.locator('#more').evaluate(el=>el.click());await selectContext('#context-library','l2');await lateMore;await page.waitForTimeout(500);
 const libraryTitles=await page.locator('h3[data-source-content="true"]').allTextContents();if(!libraryTitles.includes('B only title')||libraryTitles.includes('late A row'))failures.push(`late library response overwrote new scope: ${libraryTitles.join('|')}`);
 await selectContext('#context-library','l1');await page.waitForTimeout(100);
 await selectContext('#context-library','l2');await page.waitForTimeout(100);
 if(await page.evaluate(()=>localStorage.getItem('rh-library'))!=='l2')failures.push('library switch persistence');
 const checkScope=async(workspace,library,collection)=>{await page.waitForTimeout(100);const actual=await page.evaluate(()=>({dom:{workspace:document.querySelector('#context-workspace')?.value,library:document.querySelector('#context-library')?.value,collection:document.querySelector('#context-collection')?.value},stored:{workspace:localStorage.getItem('rh-workspace'),library:localStorage.getItem('rh-library'),collection:localStorage.getItem('rh-collection')}}));const expected={workspace,library,collection};if(JSON.stringify(actual.dom)!==JSON.stringify(expected)||JSON.stringify(actual.stored)!==JSON.stringify(expected))failures.push(`scope DOM/storage mismatch ${JSON.stringify({expected,...actual})}`);const ctx=contextRequests.at(-1),lib=libraryRequests.at(-1);if(!ctx||ctx.workspace!==workspace||ctx.library!==library||ctx.collection!==collection||!lib||lib.workspace!==workspace||lib.library!==library||lib.collection!==collection)failures.push(`scope request headers mismatch ${JSON.stringify({expected,ctx,lib})}`);rows.push({kind:'F04-scope-consistency',expected,...actual,contextRequest:ctx,libraryRequest:lib})};
 await selectContext('#context-workspace','w2');await checkScope('w2','l3','all');
 await setLocale('en');await setLocale('ja');await setLocale('zh');
 await selectContext('#context-workspace','w1');await checkScope('w1','l1','all');
 await selectContext('#context-library','l2');await checkScope('w1','l2','all');
 if(await page.locator('#more').count())failures.push('pagination cursor leaked from l1 into l2');
 await page.setViewportSize({width:1440,height:900});await page.locator('#global-search').fill('draft-w1-l2');await page.locator('[data-filter="patent"]').click();
 await selectContext('#context-workspace','w2');await checkScope('w2','l3','all');
 if(await page.locator('#global-search').inputValue()!==''||await page.locator('[data-filter="all"]').getAttribute('aria-pressed')!=='true')failures.push('draft state leaked into w2/l3');
 await selectContext('#context-workspace','w1');await checkScope('w1','l1','all');await selectContext('#context-library','l2');await checkScope('w1','l2','all');
 if(await page.locator('#global-search').inputValue()!=='draft-w1-l2'||await page.locator('[data-filter="patent"]').getAttribute('aria-pressed')!=='true')failures.push('scope-specific search/filter draft was not restored');
 await selectContext('#context-library','l1');await checkScope('w1','l1','all');
 await selectContext('#context-collection','c1');await checkScope('w1','l1','c1');
 await page.locator('#global-search').fill('draft-group-c1');await selectContext('#context-collection','all');await checkScope('w1','l1','all');
 if(await page.locator('#global-search').inputValue()!=='')failures.push('collection draft leaked to all documents');
 await selectContext('#context-collection','c1');await checkScope('w1','l1','c1');
 if(await page.locator('#global-search').inputValue()!=='draft-group-c1')failures.push('same-library collection draft was not restored');
 if(await page.evaluate(()=>localStorage.getItem('rh-language'))!=='zh'||await page.locator('#language-select').inputValue()!=='zh')failures.push('language DOM/storage did not survive three-language round trip');
 if(await page.evaluate(()=>Object.keys(localStorage).some(k=>/secret|password|api-key/i.test(k))))failures.push('secret persisted');
 await page.setViewportSize({width:750,height:700});await page.locator('#create-workspace-top').click();await page.locator('#new-workspace-dialog').waitFor();
 const dg=await page.evaluate(()=>{const d=document.querySelector('#new-workspace-dialog'),r=d.getBoundingClientRect(),n=d.querySelector('[name=name]'),l=n.closest('label').getBoundingClientRect(),t=d.querySelector('textarea').getBoundingClientRect();return {width:innerWidth,height:innerHeight,dialog:{x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom},nameWidth:n.getBoundingClientRect().width,labelWidth:l.width,descriptionHeight:t.height,nameFocused:document.activeElement===n,noteVisible:!d.querySelector('[data-empty-library-note]').hidden}});rows.push({kind:'workspace-dialog',...dg});if(dg.dialog.x<0||dg.dialog.right>dg.width||dg.dialog.y<0||dg.dialog.bottom>dg.height||Math.abs(dg.nameWidth-dg.labelWidth)>2||dg.descriptionHeight>130||!dg.nameFocused||!dg.noteVisible)failures.push(`workspace dialog geometry/focus ${JSON.stringify(dg)}`);await page.screenshot({path:join(output,'workspace-dialog-750x700.png')});await page.keyboard.press('Escape');await page.waitForFunction(()=>!document.querySelector('#new-workspace-dialog')?.open);
}finally{await browser?.close();server.close()}
const result={rows,failures};await import('node:fs/promises').then(fs=>fs.writeFile(join(output,'results.json'),JSON.stringify(result,null,2)));console.log(JSON.stringify(result,null,2));if(failures.length)process.exitCode=1;






