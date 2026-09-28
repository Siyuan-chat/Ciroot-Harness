const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

export function humanLocator(locator, t, locale) {
  if (!locator || typeof locator !== 'object') return t('evidence.locatorUnavailable',{},locale);
  const value=locator.value ?? locator.page ?? locator.paragraph ?? locator.line;
  if (value == null || value === '') return t('evidence.locatorUnavailable',{},locale);
  const kind=String(locator.kind||'').toLowerCase();
  if (kind==='pdf_page' || kind==='page') return t('evidence.locator.page',{page:value},locale);
  if (kind==='paragraph') return t('evidence.locator.paragraph',{value},locale);
  if (kind==='line' || kind==='lines') return t('evidence.locator.lines',{value},locale);
  if (kind==='claim') return t('evidence.locator.claim',{value},locale);
  return t('evidence.locator.generic',{kind:kind||t('common.unknown',{},locale),value},locale);
}

export async function loadEvidenceContext(api, evidenceId, runId, scope) {
  const response=await api.evidence(evidenceId,runId,scope);
  const evidence=response?.evidence?.items?.find(item=>item?.evidence_id===evidenceId)||response?.evidence||null;
  const sourceScope=response?.source_scope?{...scope,libraryId:response.source_scope.library_id||scope.libraryId,collectionId:'all'}:scope;
  let document=null;
  if(evidence?.document_id){
    const attempts=response?.source_scope
      ? [api.libraryDocument(evidence.document_id,sourceScope),runId?api.runDocument(runId,evidence.document_id,scope):Promise.reject(new Error('no run scope'))]
      : [runId?api.runDocument(runId,evidence.document_id,scope):Promise.reject(new Error('no run scope')),api.libraryDocument(evidence.document_id,sourceScope)];
    const values=await Promise.allSettled(attempts);
    document=values.find(value=>value.status==='fulfilled')?.value?.document||null;
  }
  return {evidence,document,sourceScope,sourceScopeInfo:response?.source_scope||null,locatorInsufficient:Boolean(response?.locator_insufficient)};
}

export function renderEvidenceInspector({context,claim=null,claims=[],t,locale}) {
  const evidence=context?.evidence,doc=context?.document;
  if(!evidence)return `<p class="inspector-empty">${t('evidence.unavailable',{},locale)}</p>`;
  const versions=Array.isArray(doc?.versions)?doc.versions:[];
  const version=versions.find(item=>item?.version_id===evidence.version_id)||versions[0];
  const rawUrl=version?.file_url||doc?.file_url;
  const fileUrl=typeof rawUrl==='string'&&rawUrl.startsWith('/api/v1/')?rawUrl:null;
  const sourceName=doc?.title||evidence.source_title||evidence.document_id||t('common.unknown',{},locale);
  const linkedClaims=(Array.isArray(claims)?claims:[]).filter(item=>Array.isArray(item?.evidence_refs)&&item.evidence_refs.some(ref=>(typeof ref==='string'?ref:ref?.evidence_id)===evidence.evidence_id));
  const displayed=claim? [claim,...linkedClaims.filter(item=>item.claim_id!==claim.claim_id)] : linkedClaims;
  return `<article class="evidence-inspector-content"><blockquote class="evidence-quote">${esc(evidence.text||evidence.quote||t('evidence.quoteUnavailable',{},locale))}</blockquote><dl class="inspector-metadata"><dt>${t('evidence.source',{},locale)}</dt><dd>${esc(sourceName)}</dd><dt>${t('evidence.version',{},locale)}</dt><dd>${esc(evidence.version_id||version?.version_id||t('common.unknown',{},locale))}</dd><dt>${t('evidence.locator',{},locale)}</dt><dd>${esc(humanLocator(evidence.locator,t,locale))}</dd></dl>${context.locatorInsufficient?`<p class="inspector-notice">${t('evidence.locatorInsufficient',{},locale)}</p>`:''}<section><h3>${t('evidence.usedBy',{},locale)}</h3>${displayed.length?`<ul>${displayed.map(item=>`<li>${esc(item.claim||item.text||item.claim_id||t('common.unknown',{},locale))}</li>`).join('')}</ul>`:`<p>${t('evidence.noLinkedClaims',{},locale)}</p>`}</section>${fileUrl?`<p><a href="${esc(fileUrl)}" target="_blank" rel="noopener">${t('evidence.openOriginal',{},locale)}</a></p>`:`<p class="inspector-notice">${t('evidence.originalUnavailable',{},locale)}</p>`}<details class="inspector-advanced"><summary>${t('evidence.advanced',{},locale)}</summary><dl><dt>evidence_id</dt><dd>${esc(evidence.evidence_id||t('common.unknown',{},locale))}</dd><dt>document_id</dt><dd>${esc(evidence.document_id||t('common.unknown',{},locale))}</dd><dt>version_id</dt><dd>${esc(evidence.version_id||t('common.unknown',{},locale))}</dd><dt>locator</dt><dd><code>${esc(JSON.stringify(evidence.locator??null))}</code></dd><dt>scope</dt><dd><code>${esc(JSON.stringify(context.sourceScopeInfo||context.sourceScope||null))}</code></dd></dl></details></article>`;
}
