const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
export function renderEvidenceTrace({claim,evidence=[],bibliography=[],t,locale}){
  const byEvidence=new Map((Array.isArray(evidence)?evidence:[]).map(item=>[item.evidence_id,item]));
  const bySource=new Map();for(const item of Array.isArray(bibliography)?bibliography:[]){if(item?.id)bySource.set(item.id,item);if(item?.document_id)bySource.set(item.document_id,item)}
  const refs=Array.isArray(claim?.evidence_refs)?claim.evidence_refs:[];
  if(!refs.length)return `<p class="evidence-trace-empty">${t('report.noEvidenceRefs',{},locale)}</p>`;
  return `<div class="evidence-trace" aria-label="${t('report.evidenceRefs',{},locale)}">${refs.map(ref=>{const id=typeof ref==='string'?ref:ref?.evidence_id;const item=id?byEvidence.get(id):null;const source=bySource.get(item?.document_id);return id&&item?`<button type="button" class="evidence-chip" data-evidence-id="${esc(id)}" data-claim-id="${esc(claim.claim_id||'')}"><span>${esc(source?.title||item.document_id||t('common.unknown',{},locale))}</span><span>${esc(item.locator?.kind&&item.locator?.value!=null?`${item.locator.kind} ${item.locator.value}`:t('evidence.locatorUnavailable',{},locale))}</span></button>`:`<span class="evidence-chip evidence-chip-unavailable" aria-disabled="true">${t('report.evidenceUnavailable',{},locale)} · ${esc(id||t('common.unknown',{},locale))}</span>`}).join('')}</div>`;
}
