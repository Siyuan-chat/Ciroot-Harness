import {renderStatusBadge} from '../components/status-badge.js';

const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const unknown=(t,locale)=>t('common.unknown',{},locale);
const shown=(value,t,locale)=>value==null||value===''?unknown(t,locale):escape(value);
const records=value=>Array.isArray(value)?value:null;
const evidenceId=ref=>typeof ref==='string'?ref:ref?.evidence_id;
const verified=claim=>claim?.verification===true||claim?.verification==='verified'||claim?.verification?.status==='verified';
const stageIndex={planning:0,source:1,acquire_normalize:2,analysis:3,verification:4,completed:5};
const stageNode={plan:['planning_gate'],search:['source_task'],read:['acquire_normalize'],analyze:['analysis_task'],verify:['verification_gate']};
const stageLabel={planning:'investigation.stagePlanning',source:'investigation.stageSearch',acquire_normalize:'investigation.stageRead',analysis:'investigation.stageAnalyze',verification:'investigation.stageVerify',completed:'investigation.stageCompleted'};
const stepIndex={plan:0,search:1,read:2,analyze:3,verify:4,review:5};

export function isCurrentInvestigationResponse({scope,currentScope,runId,selectedRunId,responseRunId,generation,currentGeneration}){
  return generation===currentGeneration&&scope?.workspaceId===currentScope?.workspaceId&&scope?.libraryId===currentScope?.libraryId&&scope?.collectionId===currentScope?.collectionId&&runId===selectedRunId&&runId===responseRunId;
}

export async function fetchInvestigationList(api,scope){
  const data=await api.runs(null,scope);
  return {runs:Array.isArray(data)?data:Array.isArray(data?.items)?data.items:[],next:data?.next_cursor??null};
}

export function projectInvestigationProgress({run={},coverage,evidenceDocuments=null,claims=null,issues=null,outcome=null}={}){
  const trace=Array.isArray(run.stage_trace)?run.stage_trace:[];
  const currentStage=stageIndex[run.stage];
  const steps=['plan','search','read','analyze','verify','review'].map(key=>{
    const nodes=stageNode[key]||[];
    const events=trace.filter(item=>item&&typeof item==='object'&&nodes.includes(item.node));
    const event=events.at(-1)?.event;
    const index=stepIndex[key];
    let state='unknown';
    if(events.some(item=>['failed','source_partial','blocked','policy_blocked','unsupported'].includes(item.event)))state='warning';
    else if((key==='plan'&&events.some(item=>item.event==='planned'))||(key==='search'&&events.some(item=>item.event==='screened'))||(key==='read'&&events.some(item=>item.event==='normalized'))||(key==='analyze'&&events.some(item=>item.event==='analyzed'))||(key==='verify'&&events.length))state='done';
    else if(Number.isFinite(currentStage)&&currentStage>index)state='done';
    else if(Number.isFinite(currentStage)&&currentStage===index)state='active';
    if(key==='search'&&Array.isArray(coverage?.queries)&&coverage.queries.some(query=>['failed','policy_blocked','partial','unsupported'].includes(query?.status)))state='warning';
    if(key==='read'&&Array.isArray(issues)&&issues.some(issue=>issue?.code==='RH_NORMALIZE_XML'&&issue?.status==='open'))state='warning';
    return {key,state,detail:null};
  });
  const detail=(key,value)=>({key,count:value});
  const queries=records(coverage?.queries);
  steps.find(step=>step.key==='search').detail=queries?detail('investigation.queryCount',queries.length):null;
  steps.find(step=>step.key==='read').detail=evidenceDocuments==null?null:detail('investigation.evidenceDocuments',evidenceDocuments);
  steps.find(step=>step.key==='analyze').detail=records(claims)?detail('investigation.claimCount',claims.length):null;
  steps.find(step=>step.key==='verify').detail=records(claims)?detail('investigation.verifiedClaimCount',claims.filter(verified).length):null;
  const review=steps.find(step=>step.key==='review');
  if(records(issues)){
    const open=issues.filter(issue=>issue?.status==='open').length;
    review.state=open?'warning':(['completed','partial','failed','stopped','policy_blocked'].includes(run.status)?'done':'active');
    review.detail=detail('investigation.openIssueCount',open);
  }
  return steps;
}

function renderTechnicalIdentity(run,t,locale){return `<details class="investigation-identity"><summary>${t('investigation.identifiers',{},locale)}</summary><dl><dt>run_id</dt><dd>${shown(run?.run_id,t,locale)}</dd><dt>project_id</dt><dd>${shown(run?.project_id,t,locale)}</dd></dl></details>`}

export function renderInvestigationList({runs=[],recentRuns=[],loading=false,hasMore=false,t,locale}){
  const recent=new Map((Array.isArray(recentRuns)?recentRuns:[]).map(item=>[item.run_id,item]));
  const items=Array.isArray(runs)?runs:[];
  const content=items.length?`<ul class="investigation-list">${items.map(run=>{const summary=recent.get(run.run_id)||{};const title=summary.research_question||run.project_id||run.run_id;const outcome=summary.outcome||run.outcome||run.status;return `<li><article class="investigation-list-item"><button type="button" data-open-investigation="${escape(run.run_id)}"><span class="investigation-list-title">${escape(title||unknown(t,locale))}</span>${renderStatusBadge(outcome,t,locale)}<span class="investigation-list-meta">${t('investigation.stage',{stage:t(stageLabel[run.stage]||'investigation.unknownStage',{status:run.stage||''},locale)},locale)}${summary.synthetic===true||run.synthetic===true?` · ${t('investigation.synthetic',{},locale)}`:''}</span></button></article></li>`}).join('')}</ul>`:`<div class="empty investigation-list-empty" role="status">${t(loading?'investigation.loading':'investigation.noRuns',{},locale)}</div>`;
  return `<section class="investigation-list-page"><header class="investigation-list-header"><div><p class="overview-eyebrow">${t('nav.investigations',{},locale)}</p><h1>${t('investigation.listTitle',{},locale)}</h1></div>${loading?`<span role="status">${t('investigation.loading',{},locale)}</span>`:''}</header>${content}${hasMore?`<button id="more">${t('investigation.loadMore',{},locale)}</button>`:''}</section>`;
}

function renderIssueList(issues,t,locale){
  if(!issues)return `<p class="investigation-muted">${t('investigation.issuesUnknown',{},locale)}</p>`;
  if(!issues.length)return `<p class="investigation-muted">${t('investigation.noIssues',{},locale)}</p>`;
  return `<ul class="investigation-issues">${issues.map(issue=>`<li><article class="investigation-issue"><header><strong>${shown(issue?.code||issue?.type,t,locale)}</strong>${renderStatusBadge(issue?.status,t,locale)}</header><p>${shown(issue?.reason||issue?.message,t,locale)}</p>${issue?.document_id?`<p>${t('investigation.issueDocument',{id:shown(issue.document_id,t,locale)},locale)}</p>`:''}${issue?.source?`<p>${t('investigation.issueSource',{source:shown(issue.source,t,locale)},locale)}</p>`:''}${issue?.impact?`<p>${t('investigation.issueImpact',{impact:shown(issue.impact,t,locale)},locale)}</p>`:''}</article></li>`).join('')}</ul>`;
}

export function renderInvestigationWorkspace({run,result,reportData,tasks=[],events=[],tab='overview',loading=false,t,locale}){
  const claims=records(reportData?.claims);
  const evidence=records(reportData?.evidence)||records(result?.evidence);
  const issues=records(result?.issues);
  const outcome=result?.outcome||run?.outcome||run?.status;
  const question=reportData?.research_question||null;
  const bibliography=records(reportData?.bibliography)||[];
  const documents=new Map();
  for(const item of evidence||[])if(item?.document_id)documents.set(item.document_id,item);
  const evidenceDocuments=evidence?documents.size:null;
  const verifiedCount=claims?claims.filter(verified).length:null;
  const openIssues=issues?issues.filter(issue=>issue?.status==='open').length:null;
  const patentDocuments=bibliography.filter(item=>typeof item?.type==='string'&&item.type.toLowerCase()==='patent');
  const steps=projectInvestigationProgress({run,coverage:run?.coverage,evidenceDocuments,claims,issues,outcome});
  const progress=`<ol class="investigation-progress">${steps.map(step=>`<li class="progress-${step.state}"><span class="progress-icon" aria-hidden="true">${step.state==='done'?'✓':step.state==='warning'?'!':step.state==='active'?'●':'·'}</span><span class="progress-label">${t('investigation.progress.'+step.key,{},locale)}</span>${step.detail?`<span class="progress-detail">${t(step.detail.key,{count:shown(step.detail.count,t,locale)},locale)}</span>`:''}</li>`).join('')}</ol>`;
  const queries=records(run?.coverage?.queries);
  const sourcePanel=queries?queries.length?`<ul class="investigation-source-list">${queries.map(query=>`<li><article><header><strong>${shown(query?.source,t,locale)}</strong>${renderStatusBadge(query?.status,t,locale)}</header><p>${shown(query?.query,t,locale)}</p><p class="investigation-muted">${t('investigation.candidates',{count:shown(query?.candidate_count,t,locale)},locale)}${query?.reason?` · ${escape(query.reason)}`:''}</p></article></li>`).join('')}</ul>`:`<p class="investigation-muted">${t('investigation.noQueries',{},locale)}</p>`:`<p class="investigation-muted">${t('investigation.sourcesUnknown',{},locale)}</p>`;
  const claimsPanel=claims?claims.length?`<section class="investigation-claims"><h2>${t('investigation.claimsTitle',{},locale)}</h2>${claims.map((claim,index)=>`<article class="investigation-claim"><header><span class="claim-order">${index+1}</span>${renderStatusBadge(verified(claim)?'verified':claim?.verification?.status||claim?.verification||claim?.status,t,locale)}</header><p>${shown(claim?.claim||claim?.text,t,locale)}</p><p class="investigation-muted">${t('investigation.evidenceRefs',{count:shown(Array.isArray(claim?.evidence_refs)?claim.evidence_refs.length:null,t,locale)},locale)}</p>${Array.isArray(claim?.evidence_refs)?`<div class="investigation-claim-evidence">${claim.evidence_refs.map((ref,refIndex)=>{const id=evidenceId(ref);return id?`<button type="button" data-evidence-id="${escape(id)}">${t('investigation.evidenceLink',{index:refIndex+1},locale)}</button>`:''}).join('')}</div>`:''}<details><summary>${t('investigation.identifiers',{},locale)}</summary><code>${shown(claim?.claim_id,t,locale)}</code></details></article>`).join('')}</section>`:`<p class="investigation-muted">${t('investigation.noClaims',{},locale)}</p>`:`<p class="investigation-muted">${t('investigation.claimsUnknown',{},locale)}</p>`;
  const bibliographicTitles=new Map();
  for(const item of bibliography){if(item?.id)bibliographicTitles.set(item.id,item);if(item?.document_id)bibliographicTitles.set(item.document_id,item)}
  const evidencePanel=evidence?evidence.length?`<ul class="investigation-evidence-list">${evidence.map(item=>{const source=bibliographicTitles.get(item?.document_id)||{};const locator=item?.locator?.kind&&item?.locator?.value!=null?`${item.locator.kind} · ${item.locator.value}`:unknown(t,locale);const usedBy=claims?claims.filter(claim=>Array.isArray(claim?.evidence_refs)&&claim.evidence_refs.some(ref=>evidenceId(ref)===item?.evidence_id)).length:null;return `<li><article><h3>${shown(source.title||item?.document_id,t,locale)}</h3><blockquote>${shown(item?.text||item?.quote,t,locale)}</blockquote><p>${t('investigation.locator',{locator:escape(locator)},locale)}</p><p class="investigation-muted">${t('investigation.usedByClaims',{count:shown(usedBy,t,locale)},locale)}</p>${item?.evidence_id?`<button type="button" data-evidence-id="${escape(item.evidence_id)}">${t('investigation.openEvidence',{},locale)}</button>`:''}<details><summary>${t('investigation.identifiers',{},locale)}</summary><code>${shown(item?.evidence_id,t,locale)} · ${shown(item?.document_id,t,locale)} · ${shown(item?.version_id,t,locale)}</code></details></article></li>`}).join('')}</ul>`:`<p class="investigation-muted">${t('investigation.noEvidence',{},locale)}</p>`:`<p class="investigation-muted">${t('investigation.evidenceUnknown',{},locale)}</p>`;
  const activityRows=Array.isArray(events)&&events.length?events.slice().sort((a,b)=>(a?.seq||0)-(b?.seq||0)).map(item=>({time:item?.time,stage:item?.payload?.stage||item?.payload?.node,event:item?.payload?.status||item?.payload?.event||item?.type})):Array.isArray(run?.stage_trace)?run.stage_trace.map(item=>({stage:item?.node,event:item?.event})):[];
  const activity=activityRows.length?`<ol class="investigation-activity">${activityRows.map(item=>{const stage=item.stage? t(stageLabel[item.stage]||'investigation.unknownStage',{status:escape(item.stage)},locale):unknown(t,locale);const event=item.event? t('investigation.rawEvent',{status:escape(item.event)},locale):unknown(t,locale);const time=Number.isFinite(Number(item.time))?new Date(Number(item.time)*1000).toLocaleTimeString(locale):'';return `<li>${time?`<time>${escape(time)}</time>`:''}<span>${t('investigation.activityEntry',{stage,event},locale)}</span></li>`}).join('')}</ol>`:`<p class="investigation-muted">${t('investigation.noActivity',{},locale)}</p>`;
  const patentPanel=patentDocuments.length?`<ul class="investigation-patents">${patentDocuments.map(item=>`<li><article><h3>${shown(item.title,t,locale)}</h3><p>${shown(item.publication_id||item.publication_number,t,locale)}</p><details><summary>${t('investigation.identifiers',{},locale)}</summary><code>${shown(item.id,t,locale)}</code></details></article></li>`).join('')}</ul>`:'';
  const tabs=[['overview','investigation.tabOverview'],['sources','investigation.tabSources'],['evidence','investigation.tabEvidence'],['activity','investigation.tabActivity'],...(patentDocuments.length?[['patent-compare','investigation.tabPatent']]:[])];
  const summary=`<div class="investigation-summary"><article><strong>${shown(verifiedCount,t,locale)}</strong><span>${t('investigation.verifiedClaimsLabel',{},locale)}</span></article><article><strong>${shown(openIssues,t,locale)}</strong><span>${t('investigation.openIssuesLabel',{},locale)}</span></article><article><strong>${shown(evidenceDocuments,t,locale)}</strong><span>${t('investigation.evidenceDocumentsLabel',{},locale)}</span></article><article><strong>${t('investigation.coverage',{status:run?.coverage?.complete===true?t('coverage.complete',{},locale):run?.coverage?.complete===false?t('coverage.partial',{},locale):unknown(t,locale)},locale)}</strong><span>${t('investigation.sourceCoverage',{},locale)}</span></article></div>`;
  let panel=tab==='sources'?`<section><h2>${t('investigation.sourcesTitle',{},locale)}</h2>${sourcePanel}</section>`:tab==='evidence'?`<section><h2>${t('investigation.evidenceTitle',{},locale)}</h2>${evidencePanel}${claimsPanel}</section>`:tab==='activity'?`<section><h2>${t('investigation.activityTitle',{},locale)}</h2>${activity}${tasks.length?`<p class="investigation-muted">${t('investigation.pendingTasks',{count:tasks.length},locale)}</p>`:''}</section>`:tab==='patent-compare'?`<section><h2>${t('investigation.tabPatent',{},locale)}</h2>${patentPanel}</section>`:`<section class="investigation-overview">${summary}<section><h2>${t('investigation.progressTitle',{},locale)}</h2>${progress}</section><section id="investigation-issues"><header><h2>${t('investigation.issuesTitle',{},locale)}</h2>${openIssues?renderStatusBadge('needs_review',t,locale):''}</header>${renderIssueList(issues,t,locale)}</section>${claimsPanel}</section>`;
  return `<article class="investigation-workspace"><button type="button" class="investigation-back" data-investigation-list>${t('investigation.backToList',{},locale)}</button><header class="investigation-header"><div><p class="overview-eyebrow">${t('nav.investigations',{},locale)}</p><h1>${shown(question||run?.project_id||run?.run_id,t,locale)}</h1>${question?`<p class="investigation-question">${escape(question)}</p>`:''}${run?.waiting_reason?`<p class="investigation-waiting-reason">${t('investigation.waitingReason',{reason:escape(run.waiting_reason)},locale)}</p>`:''}</div><div class="investigation-status">${renderStatusBadge(outcome,t,locale)}${run?.synthetic===true||result?.synthetic===true?`<span class="badge partial">${t('investigation.synthetic',{},locale)}</span>`:''}</div></header><div class="investigation-header-metrics"><span>${t('investigation.verifiedCount',{count:shown(verifiedCount,t,locale)},locale)}</span><span>${t('investigation.issueCount',{count:shown(openIssues,t,locale)},locale)}</span></div><div class="investigation-actions"><button type="button" data-open-investigation-report>${t('investigation.openReport',{},locale)}</button><button type="button" data-investigation-review-issues>${t('investigation.reviewIssues',{},locale)}</button></div><nav class="investigation-tabs" aria-label="${t('investigation.tabsLabel',{},locale)}">${tabs.map(([key,label])=>`<button type="button" data-investigation-tab="${key}" aria-current="${tab===key?'page':'false'}">${t(label,{},locale)}</button>`).join('')}</nav><p class="investigation-scope">${t('investigation.scopeSummary',{candidates:shown(run?.coverage?.candidate_count,t,locale),evidenceDocuments:shown(evidenceDocuments,t,locale),coverage:run?.coverage?.complete===true?t('coverage.complete',{},locale):run?.coverage?.complete===false?t('coverage.partial',{},locale):unknown(t,locale)},locale)}</p>${loading?`<p role="status">${t('investigation.loading',{},locale)}</p>`:''}<div class="investigation-panel">${panel}</div>${renderTechnicalIdentity(run,t,locale)}</article>`;
}
