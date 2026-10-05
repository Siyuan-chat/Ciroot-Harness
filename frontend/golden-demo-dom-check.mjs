import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, join, extname } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

if(!process.env.PLAYWRIGHT_MODULE||!process.env.EDGE_EXECUTABLE)throw new Error('Set PLAYWRIGHT_MODULE and EDGE_EXECUTABLE to use the bundled browser test runtime.');
const {chromium}=await import(pathToFileURL(resolve(process.env.PLAYWRIGHT_MODULE)).href);
const frontendRoot=resolve(fileURLToPath(new URL('.',import.meta.url)),'dist');
const requests=[],completed=[];
const holds={GET:false,POST:false}, gates={GET:[],POST:[]};let hasDemo=false,failNextPost=false;
async function waitForRecorded(method,after){for(let i=0;i<100;i++){if(requests.slice(after).some(x=>x.method===method))return;await new Promise(resolve=>setTimeout(resolve,10))}throw new Error(`Server did not record ${method} request`)}
async function waitForGate(method){for(let i=0;i<100;i++){if(gates[method].length)return;await new Promise(resolve=>setTimeout(resolve,10))}throw new Error(`Server did not hold ${method} response`)}
async function waitForCompleted(method,after){for(let i=0;i<100;i++){if(completed.slice(after).includes(method))return;await new Promise(resolve=>setTimeout(resolve,10))}throw new Error(`Server did not complete ${method} response`)}
const demo={workspace_label:'Golden Demo',run_id:'dom-demo-1',status:{status:'partial',stage:'completed',outcome:'partial',synthetic:true,coverage:{queries:[{query_id:'q1',source:'synthetic-paper',query:'paper query',status:'complete'},{query_id:'q2',source:'synthetic-patent',query:'patent query',status:'complete'}],attempts:[{query_id:'q1',attempt:1,status:'success'},{query_id:'q2',attempt:1,status:'success'}]},stage_trace:[{node:'acquire_normalize',event:'source_failure',code:'RH_NORMALIZE_XML',status:'open',document_id:'paper-review-gap',version_id:'v1',message:'invalid XML'}]},spec:{status:'ready',project_id:'synthetic-d19',revision:1,research_question:'Compare synthetic membrane routes.',report_targets:['technical_report','literature_review'],references:[]},result:{issues:[{code:'RH_NORMALIZE_XML',status:'open',document_id:'paper-review-gap',version_id:'v1',message:'invalid XML'}],evidence:[]},report_data:{claims:[],evidence:[],sections:[]},reports:[{type:'technical_report',language:'en',format:'markdown',content:'TECHNICAL BODY'},{type:'literature_review',language:'en',format:'markdown',content:'LITERATURE BODY'}]};
const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.png':'image/png'};
const server=createServer(async(req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname.startsWith('/api/v1/')){
    let body='';for await(const chunk of req)body+=chunk;
    requests.push({path:url.pathname,method:req.method,headers:req.headers,body});
    if(url.pathname==='/api/v1/golden-demo'&&holds[req.method])await new Promise(resolve=>gates[req.method].push(resolve));
    res.setHeader('content-type','application/json');
    if(url.pathname==='/api/v1/registry'){res.end(JSON.stringify({schema_version:'1',workspaces:[]}));return}
    if(url.pathname==='/api/v1/golden-demo'&&req.method==='GET'){completed.push('GET');res.end(JSON.stringify({schema_version:'1',demo:hasDemo?demo:null}));return}
    if(url.pathname==='/api/v1/golden-demo'&&req.method==='POST'){if(failNextPost){failNextPost=false;res.statusCode=503;completed.push('POST');res.end(JSON.stringify({code:'TEMPORARY_FAILURE',message:'retry required'}));return}hasDemo=true;completed.push('POST');res.end(JSON.stringify({schema_version:'1',demo}));return}
    res.end(JSON.stringify({schema_version:'1'}));return;
  }
  const relative=url.pathname==='/'?'index.html':decodeURIComponent(url.pathname.slice(1));
  const file=resolve(frontendRoot,relative);
  if(!file.startsWith(frontendRoot)){res.statusCode=403;res.end('Forbidden');return}
  try{res.setHeader('content-type',mime[extname(file)]||'application/octet-stream');res.end(await readFile(file))}catch{res.statusCode=404;res.end('Not found')}
});
let browser;
try{
  await new Promise(resolveListen=>server.listen(0,'127.0.0.1',resolveListen));
  browser=await chromium.launch({headless:true,executablePath:process.env.EDGE_EXECUTABLE});
  const page=await browser.newPage({viewport:{width:1280,height:850}});
  const pageErrors=[];page.on('pageerror',error=>pageErrors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const cta=page.locator('#top-demo');await cta.waitFor({state:'visible'});
  for(const [locale,expected] of [['en','Try Demo'],['zh','试用 Demo'],['ja','Demo を試す']]){
    await page.locator('#language-select').evaluate((el, value)=>{el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}))},locale);
    await assert.equal(await cta.textContent(),expected);
  }
  const getResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/golden-demo'&&r.request().method()==='GET');
  await cta.click();await getResponse;
  await page.getByRole('main',{name:'Golden Demo'}).waitFor();
  assert.equal(await page.locator('.golden-demo [data-demo-run]').isVisible(),true);
  const postResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/golden-demo'&&r.request().method()==='POST');
  await page.locator('[data-demo-run]').click();await postResponse;
  await page.getByText('dom-demo-1').waitFor();
  await page.locator('[data-demo-tab="sources"]').click();
  assert.equal(await page.locator('.demo-card').filter({hasText:'paper query'}).count(),1);
  assert.equal(await page.locator('.demo-card').filter({hasText:'success'}).count(),2);
  await page.locator('[data-demo-tab="review"]').click();
  await page.getByText('RH_NORMALIZE_XML').waitFor();await page.getByText('invalid XML').waitFor();
  await page.locator('[data-demo-home]').click();
  assert.equal(await page.locator('.golden-demo').count(),0,'Back to workspace must leave the demo page');
  holds.GET=true;
  const beforeStaleGet=requests.length;
  const completedBeforeStaleGet=completed.length;
  await page.locator('#top-demo').click();await waitForRecorded('GET',beforeStaleGet);await waitForGate('GET');
  await page.locator('[data-demo-home]').click();holds.GET=false;gates.GET.splice(0).forEach(release=>release());await waitForCompleted('GET',completedBeforeStaleGet);
  const recoveredGet=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/golden-demo'&&r.request().method()==='GET');
  await page.locator('#top-demo').click();await recoveredGet;
  assert.equal(await page.locator('[data-demo-fresh]').isEnabled(),true,'delayed GET must not leave the re-entered demo busy');
  await page.locator('[data-demo-home]').click();
  hasDemo=false;holds.POST=true;failNextPost=true;
  const beforeStalePost=requests.length;
  const completedBeforeStalePost=completed.length;
  const stalePostRequest=page.waitForRequest(r=>new URL(r.url()).pathname==='/api/v1/golden-demo'&&r.method()==='POST');
  const initialDemoRead=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/golden-demo'&&r.request().method()==='GET');
  await page.locator('#top-demo').click();await initialDemoRead;
  await page.locator('[data-demo-run]').click();const firstPost=await stalePostRequest;await waitForRecorded('POST',beforeStalePost);await waitForGate('POST');const firstKey=firstPost.headers()['idempotency-key'];
  await waitForGate('POST');await page.locator('[data-demo-home]').click();holds.POST=false;gates.POST.splice(0).forEach(release=>release());await waitForCompleted('POST',completedBeforeStalePost);
  const postRecoveryGet=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/golden-demo'&&r.request().method()==='GET');
  await page.locator('#top-demo').click();await postRecoveryGet;
  assert.equal(await page.locator('[data-demo-run]').isEnabled(),true,'failed stale POST must not leave the re-entered demo busy');
  const retry=page.waitForRequest(r=>new URL(r.url()).pathname==='/api/v1/golden-demo'&&r.method()==='POST');
  const retryResponse=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/golden-demo'&&r.request().method()==='POST');
  await page.locator('[data-demo-run]').click();const retryRequest=await retry;await retryResponse;
  assert.equal(retryRequest.headers()['idempotency-key'],firstKey,'retry after leaving an in-flight POST must preserve its idempotency identity');
  await page.locator('[data-demo-home]').click();
  const inline=page.locator('#top-demo');await inline.waitFor({state:'visible'});
  const inlineRead=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/golden-demo'&&r.request().method()==='GET');
  await inline.click();await inlineRead;
  const demoCalls=requests.filter(x=>x.path==='/api/v1/golden-demo');
  assert.deepEqual(demoCalls.map(x=>x.method),['GET','POST','GET','GET','GET','POST','GET','POST','GET']);
  assert.equal(Object.hasOwn(demoCalls[0].headers,'x-workspace-id'),false);
  assert.equal(demoCalls[1].body,'{}');assert.ok(demoCalls[1].headers['idempotency-key']);
  assert.deepEqual(pageErrors,[]);
  console.log(JSON.stringify({status:'PASS',actualDomClicks:7,lifecycle:'delayed GET and POST leave/re-enter recovered',retryIdentityPreserved:true,canonicalPostBody:demoCalls.find(x=>x.method==='POST').body,requests:demoCalls.map(x=>x.method),pageErrors}));
} finally {await browser?.close();server.close()}
