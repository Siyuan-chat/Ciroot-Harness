import {renderStatusBadge} from '../components/status-badge.js';

const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const unknown=(t,locale)=>t('common.unknown',{},locale);
const count=(value,t,locale)=>value==null?unknown(t,locale):String(value);
const verified=claim=>claim?.verification===true||claim?.verification==='verified'||claim?.verification?.status==='verified';
const stageOrder={planning:0,source:1,acquire_normalize:2,analysis:3,verification:4,completed:5};
const stepStage={plan:0,search:1,read:2,analyze:3,verify:4,review:5};
const stageNames={planning:'investigation.stagePlanning',source:'investigation.stageSearch',acquire_normalize:'investigation.stageRead',analysis:'investigation.stageAnalyze',verification:'investigation.stageVerify',completed:'investigation.stageCompleted'};
const traceNodes={plan:['planning_gate'],search:['source_task'],read:['acquire_normalize'],analyze:['analysis_task'],verify:['verification_gate']};

export function isCurrentInvestigationResponse({scope,currentScope,runId,selectedRunId,responseRunId,generation,currentGeneration}){
  return generation===currentGeneration&&scope?.workspaceId===currentScope?.workspaceId&&scope?.libraryId===currentScope?.libraryId&&scope?.collectionId===currentScope?.collectionId&&runId===selectedRunId&&runId===responseRunId;
}

export async function fetchInvestigationList(api,scope){
  const data=await api.runs(null,scope);
  return {runs:Array.isArray(data)?data:Array.isArray(data?.items)?data.items:[],next:data?.next_cursor??null};
}

export function projectInvestigationProgress({run={},coverage, evidenceCount=null, claims=null, issues=null, outcome=null}={}){
  const trace=Array.isArray(run.stage_trace)?run.stage_trace:[];
  const stage=stageOrder[run.stage];
  const mapped=['plan','search','read','analyze','verify','review'].map(key=>{
    const node=traceNodes[key]||[];
    const events=trace.filter(item=>item&&node.includes(item.node));
    const event=events.at(-1)?.event;
    const index=stepStage[key];
    let state='unknown';
    if(events.length&&['failed','source_partial','blocked','policy_blocked'].includes(event))state='warning';
    else if((key==='plan'&&events.some(item=>item.event==='planned'))||(key==='search'&&events.some(item=>item.event==='screened'))||(key==='read'&&events.some(item=>item.event==='normalized'))||(key==='analyze'&&events.some(item=>item.event==='analyzed'))||(key==='verify'&&events.length))state='done';
    else if(Number.isFinite(stage)&&stage>index)state='done';
    else if(Number.isFinite(stage)&&stage===index)state='active';
    if(key==='search'&&Array.isArray(coverage?.queries)&&coverage.queries.some(item=>['failed','policy_blocked','partial','unsupported'].includes(item.status)))state='warning';
    if(key==='read'&&Array.isArray(issues)&&issues.some(item=>item.code==='RH_NORMALIZE_XML'&&item.status==='open'))state='warning';
    if(key==='verify'&&outcome==='partial'&&(!events.length||['failed','unsupported'].includes(event)))state='warning';
    return {key,state,detail:null};
  });
  const read=mapped.find(item=>item.key==='read');
  read.detail=evidenceCount==null?null:{key:'investigation.evidenceCount',count:evidenceCount};
  const analyze=mapped.find(item=>item.key==='analyze');
  analyze.detail=Array.isArray(claims)?{key:'investigation.claims',count:claims.length}:null;
  const verify=mapped.find(item=>item.key==='verify');
  const verifiedCount=Array.isArray(claims)?claims.filter(verified).length:null;
  verify.detail=verifiedCount==null?null:{key:'investigation.verifiedCount',count:verifiedCount};
  const review=mapped.find(item=>item.key==='review');
  if(Array.isArray(issues)){
    const open=issues.filter(issue=>issue?.status==='open').length;
    review.state=open?'warning':(run.status==='completed'||run.status==='partial'||run.status==='failed'||run.status==='stopped'?'done':'active');
    review.detail={key:'investigation.issueCount',count:open};
  }
  return mapped;
}

function renderTechnicalIdentity(run,t,locale){return `<details class="investigation-identity"><summary>${t('investigation.identifiers',{},locale)}</summary><dl><dt>run_id</dt><dd>${escape(run?.run_id||unknown(t,locale))}</dd></dl></details>`}

export function renderInvestigationList({runs=[],recentRuns=[],loading=false,hasMore=false,t,locale}){
  const recent=new Map((Array.isArray(recentRuns)?recentRuns:[]).map(item=>[item.run_id,item]));
  const items=Array.isArray(runs)?runs:[];
  const content=items.length?`<ul class="investigation-list">${items.map(run=>{const projected=recent.get(run.run_id)||{};const title=projected.research_question||run.project_id||run.run_id||unknown(t,locale);const status=projected.outcome||run.outcome||run.status;return `<li><article class="investigation-list-item"><button type="button" data-open-investigation="${escape(run.run_id)}"><span class="investigation-list-title">${escape(title)}</span>${renderStatusBadge(status,t,locale)}<span class="investigation-list-meta">${t('investigation.stage',{stage:t(stageNames[run.stage]||'common.unknown',{status:run.stage||''},locale)},locale)}${projected.synthetic===true||run.synthetic===true?` · ${t('investigation.synthetic',{},locale)}`:''}</span></button><details class="investigation-list-id"><summary>${t('investigation.identifiers',{},locale)}</summary><code>${escape(run.run_id)}</code></details></article></li>`}).join('')}</ul>`:`<div class="empty investigation-list-empty" role="status">${t(loading?'investigation.loading':'investigation.noRuns',{},locale)}</div>`;
  return `<section class="investigation-list-page"><header class="investigation-list-header"><div><p class="overview-eyebrow">${t('nav.investigations',{},locale)}</p><h1>${t('investigation.listTitle',{},locale)}</h1></div>${loading?`<span role="status">${t('investigation.loading',{},locale)}</span>`:''}</header>${content}${hasMore?`<button id="more">${t('investigation.loadMore',{},locale)}</button>`:''}</section>`;
}

export function renderInvestigationWorkspace({run,result,reportData,tasks=[],events=[],tab='overview',loading=false,canAdvance=false,canStop=false,canResume=false,t,locale}){
  const claims=Array.isArray(reportData?.claims)?reportData.claims:null;
  const evidence=Array.isArray(reportData?.evidence)?reportData.evidence:Array.isArray(result?.evidence)?result.evidence:null;
  const issues=Array.isArray(result?.issues)?result.issues:null;
  const outcome=result?.outcome||run?.outcome||run?.status;
  const question=reportData?.research_question||null;
  const verifiedCount=claims?claims.filter(verified).length:null;
  const openIssues=issues?issues.filter(issue=>issue?.status==='open').length:null;
  const patentDocuments=(Array.isArray(reportData?.bibliography)?reportData.bibliography:[]).filter(item=>typeof item?.type==='string'&&item.type.toLowerCase()==='patent');
  const steps=projectInvestigationProgress({run,coverage:run?.coverage,evidenceCount:evidence?.length??null,claims,issues,outcome});
  const status=renderStatusBadge(outcome,t,locale);
  const synthetic=run?.synthetic===true||result?.synthetic===true||reportData?.synthetic===true;
  const tabs=[['overview','investigation.tabOverview'],['sources','investigation.tabSources'],['evidence','investigation.tabEvidence'],['activity','investigation.tabActivity'],...(patentDocuments.length?[['patent-compare','investigation.tabPatent']]:[])];
  const progress=`<ol class="investigation-progress">${steps.map(step=>`<li class="progress-${step.state}"><span class="progress-icon" aria-hidden="true">${step.state==='done'?'✓':step.state==='warning'?'!':step.state==='active'?'●':'·'}</span><span class="progress-label">${t('investigation.progress.'+step.key,{},locale)}</span>${step.detail?`<span class="progress-detail">${t(step.detail.key,{count:count(step.detail.count,t,locale)},locale)}</span>`:''}</li>`).join('')}</ol>`;
  const issueCards=issues?.length?`<div class="investigation-issues">${issues.map(issue=>`<article class="investigation-issue"><div><strong>${escape(issue.code||issue.type||t('investigation.issueUnknown',{},locale))}</strong>${renderStatusBadge(issue.status,t,locale)}</div><p>${escape(issue.reason||issue.message||unknown(t,locale))}</p><dl>${[['document',issue.document_id],['source',issue.source]].filter(([,value])=>value!=null).map(([key,value])=>`<dt>${t('investigation.issue.'+key,{},locale)}</dt><dd>${escape(value)}</dd>`).join('')}</dl>${issue.impact?`<p>${t('investigation.impact',{},locale)}: ${escape(issue.impact)}</p>`:''}</article>`).join('')}</div>`:`<p class="investigation-muted">${issues?t('investigation.noIssues',{},locale):t('investigation.issuesUnknown',{},locale)}</p>`;
  const sources=run?.coverage?.queries;
  const sourceTab=Array.isArray(sources)?(sources.length?`<ul class="investigation-source-list">${sources.map(query=>`<li><article><div><strong>${escape(query.source||unknown(t,locale))}</strong>${renderStatusBadge(query.status,t,locale)}</div><p>${escape(query.query||unknown(t,locale))}</p><p class="investigation-muted">${t('investigation.candidates',{count:count(query.candidate_count,t,locale)},locale)}${query.reason?` · ${escape(query.reason)}`:''}</p></article></li>`).join('')}</ul>`:`<p class="investigation-muted">${t('investigation.noQueries',{},locale)}</p>`):`<p class="investigation-muted">${t('investigation.sourcesUnknown',{},locale)}</p>`;
  const sourceCoverage=run?.coverage?.complete===true?'complete':run?.coverage?.complete===false?'partial':null;
  const bibliography=new Map((Array.isArray(reportData?.bibliography)?reportData.bibliography:[]).map(item=>[item.id,item]));
  const claimsTab=claims?.length?`<section class="investigation-claims"><h2>${t('investigation.claimsTitle',{},locale)}</h2>${claims.map((claim,index)=>`<article class="investigation-claim"><div><span class="claim-order">${index+1}</span>${renderStatusBadge(verified(claim)?'verified':claim.verification?.status||claim.verification||claim.status,t,locale)}</div><p>${escape(claim.claim||claim.text||unknown(t,locale))}</p><p class="investigation-muted">${t('investigation.evidenceRefs',{count:Array.isArray(claim.evidence_refs)?claim.evidence_refs.length:unknown(t,locale)},locale)}</p></article>`).join('')}</section>`:`<p class="investigation-muted">${claims?t('investigation.noClaims',{},locale):t('investigation.claimsUnknown',{},locale)}</p>`;
  const evidenceTab=evidence?.length?`<ul class="investigation-evidence-list">${evidence.map(item=>{const source=bibliography.get(item.document_id)||{};const locator=item.locator?.kind&&item.locator?.value!=null?`${item.locator.kind} · ${item.locator.value}`:unknown(t,locale);const usedBy=claims?.filter(claim=>claim.evidence_refs?.some(ref=>(typeof ref==='string'?ref:ref?.evidence_id)===item.evidence_id)).length;return `<li><article><h3>${escape(source.title||item.document_id||unknown(t,locale))}</h3><blockquote>${escape(item.text||item.quote||unknown(t,locale))}</blockquote><p>${t('investigation.locator',{locator:escape(locator)},locale)}</p><p class="investigation-muted">${t('investigation.usedByClaims',{count:count(usedBy,t,locale)},locale)}</p>${item.evidence_id?`<button type="button" data-evidence-id="${escape(item.evidence_id)}">${t('investigation.openEvidence',{},locale)}</button>`:''}<details><summary>${t('investigation.identifiers',{},locale)}</summary><code>${escape(item.evidence_id||unknown(t,locale))} · ${escape(item.document_id||unknown(t,locale))} · ${escape(item.version_id||unknown(t,locale))}</code></details></article></li>`}).join('')}</ul>`:`<p class="investigation-muted">${evidence?t('investigation.noEvidence',{},locale):t('investigation.evidenceUnknown',{},locale)}</p>`;
  const activity=events.length?`<ol class="investigation-activity">${events.slice().sort((a,b)=>(a.seq||0)-(b.seq||0)).map(item=>{const payload=item.payload||{};const stage=payload.stage||payload.node||item.type||unknown(t,locale);const event=payload.status||payload.event||item.type||unknown(t,locale);const summary=t('investigation.activityEntry',{stage:t(stageNames[stage]||'investigation.rawStage',{status:escape(stage)},locale),event:t('investigation.rawEvent',{status:escape(event)},locale)},locale);return `<li><time>${escape(item.time?new Date(item.time*1000).toLocaleTimeString(locale):item.seq!=null?`#${item.seq}`:unknown(t,locale))}</time><span>${summary}</span></li>`}).join('')}</ol>`:run?.stage_trace?.length?`<ol class="investigation-activity">${run.stage_trace.map(item=>`<li><span>${t('investigation.activityEntry',{stage:t(stageNames[item.node]||'investigation.rawStage',{status:escape(item.node||unknown(t,locale))},locale),event:t('investigation.rawEvent',{status:escape(item.event||unknown(t,locale))},locale)},locale)}</span></li>`).join('')}</ol>`:`<p class="investigation-muted">${t('investigation.noActivity',{},locale)}</p>`;
  const patentTab=patentDocuments.length?`<ul class="investigation-patents">${patentDocuments.map(item=>`<li><article><h3>${escape(item.title||unknown(t,locale))}</h3><p>${escape(item.publication_id||item.publication_number||unknown(t,locale))}</p><p class="investigation-muted">${escape(item.id||unknown(t,locale))}</p></article></li>`).join('')}</ul>`:'';
  let panel='';
  if(tab==='sources')panel=`<section><h2>${t('investigation.sourcesTitle',{},locale)}</h2><p>${t('investigation.coverage',{status:sourceCoverage?t('coverage.'+sourceCoverage,{},locale):unknown(t,locale)},locale)}</p>${sourceTab}</section>`;
  else if(tab==='evidence')panel=`<section><h2>${t('investigation.evidenceTitle',{},locale)}</h2>${evidenceTab}${claimsTab}</section>`;
  else if(tab==='activity')panel=`<section><h2>${t('investigation.activityTitle',{},locale)}</h2>${activity}${tasks.length?`<h3>${t('investigation.pendingTasks',{count:tasks.length},locale)}</h3><p>${t('investigation.pendingTasksHint',{},locale)}</p>`:''}</section>`;
  else if(tab==='patent-compare')panel=`<section><h2>${t('investigation.tabPatent',{},locale)}</h2>${patentTab}</section>`;
  else panel=`<section class="investigation-overview"><div class="investigation-summary"><article><strong>${count(verifiedCount,t,locale)}</strong><span>${t('investigation.verifiedClaimsLabel',{},locale)}</span></article><article><strong>${count(openIssues,t,locale)}</strong><span>${t('investigation.openIssuesLabel',{},locale)}</span></article><article><strong>${count(evidence?.length,t,locale)}</strong><span>${t('investigation.evidenceDocumentsLabel',{},locale)}</span></article><article><strong>${t('investigation.coverage',{status:sourceCoverage?t('coverage.'+sourceCoverage,{},locale):unknown(t,locale)},locale)}</strong><span>${t('investigation.sourceCoverage',{},locale)}</span></article></div><section><h2>${t('investigation.progressTitle',{},locale)}</h2>${progress}</section><section id="investigation-issues"><div class="investigation-section-heading"><h2>${t('investigation.issuesTitle',{},locale)}</h2>${issues?.some(issue=>issue.status==='open')?`<span class="status-badge status-needs_review">${t('investigation.openIssuesLabel',{},locale)} · ${count(openIssues,t,locale)}</span>`:''}</div>${issueCards}</section>${claimsTab}</section>`;
  const terminal=['completed','partial','failed','policy_blocked','stopped'];
  const nextAction=tasks.length?`<button type="button" data-investigation-tab="activity">${t('investigation.reviewTasks',{count:tasks.length},locale)}</button>`:run?.status==='stopped'&&canResume?`<button type="button" data-investigation-action="resume">${t('investigation.resume',{},locale)}</button>`:!terminal.includes(run?.status)&&canAdvance?`<button type="button" data-investigation-action="advance">${t('investigation.advance',{},locale)}</button>`:null;
  return `<article class="investigation-workspace"><button type="button" class="investigation-back" data-investigation-list>${t('investigation.backToList',{},locale)}</button><header class="investigation-header"><div><p class="overview-eyebrow">${t('nav.investigations',{},locale)}</p><h1>${escape(question||run?.project_id||run?.run_id||unknown(t,locale))}</h1>${question?`<p class="investigation-question">${escape(question)}</p>`:''}${run?.waiting_reason?`<p class="investigation-waiting-reason">${t('investigation.waitingReason',{reason:escape(run.waiting_reason)},locale)}</p>`:''}</div><div class="investigation-status">${status}${synthetic?`<span class="badge partial">${t('investigation.synthetic',{},locale)}</span>`:''}</div></header><div class="investigation-header-metrics"><span>${t('investigation.verifiedCount',{count:count(verifiedCount,t,locale)},locale)}</span><span>${t('investigation.issueCount',{count:count(openIssues,t,locale)},locale)}</span></div><div class="investigation-actions"><button type="button" data-open-investigation-report>${t('investigation.openReport',{},locale)}</button><button type="button" data-investigation-review-issues>${t('investigation.reviewIssues',{},locale)}</button>${nextAction||''}${canStop&&!terminal.includes(run?.status)?`<button type="button" data-investigation-action="stop">${t('investigation.stop',{},locale)}</button>`:''}</div><nav class="investigation-tabs" aria-label="${t('investigation.tabsLabel',{},locale)}">${tabs.map(([key,label])=>`<button type="button" data-investigation-tab="${key}" aria-current="${tab===key?'page':'false'}">${t(label,{},locale)}</button>`).join('')}</nav><p class="investigation-scope">${t('investigation.scopeSummary',{candidates:count(run?.coverage?.candidate_count,t,locale),evidenceItems:count(evidence?.length,t,locale),coverage:sourceCoverage?t('coverage.'+sourceCoverage,{},locale):unknown(t,locale)},locale)}</p>${loading?`<p role="status">${t('investigation.loading',{},locale)}</p>`:''}<div class="investigation-panel">${panel}</div>${renderTechnicalIdentity(run,t,locale)}</article>`;
}
