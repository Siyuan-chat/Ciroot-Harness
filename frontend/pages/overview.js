import { renderGoldenDemoCard } from '../components/golden-demo-card.js';
import { renderStatusBadge } from '../components/status-badge.js';

const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const count = (value, t, locale) => escape(value == null ? t('common.unknown', {}, locale) : String(value));

export function renderOverview({overview, locale, questionDraft = '', loading = false, demoStarting = false, t}) {
  const workspace = overview?.workspace;
  const recent = Array.isArray(overview?.recent_runs) ? overview.recent_runs : [];
  const runs = recent.length ? `<ul class="overview-run-list">${recent.map(run => `<li><button type="button" class="overview-run" data-open-overview-run="${escape(run.run_id)}"><span class="overview-run-title">${escape(run.research_question || run.project_id || run.run_id || t('common.unknown', {}, locale))}</span>${renderStatusBadge(run.outcome, t, locale)}<span class="overview-run-meta">${run.verified_claim_count == null ? t('overview.unknownVerifiedClaims', {}, locale) : t('overview.verifiedClaims', {count: count(run.verified_claim_count, t, locale)}, locale)} · ${run.open_issue_count == null ? t('overview.unknownOpenIssues', {}, locale) : t('overview.openIssues', {count: count(run.open_issue_count, t, locale)}, locale)}</span></button></li>`).join('')}</ul>` : `<p class="overview-empty-note">${t(loading ? 'overview.loading' : 'overview.noRecent', {}, locale)}</p>`;
  const library = overview?.library;
  return `<section class="overview-page">
    <header class="overview-welcome"><p class="overview-eyebrow">${t('nav.overview', {}, locale)}</p><h1>${escape(workspace?.name || t('common.unknown', {}, locale))}</h1>
      <label for="overview-question">${t('overview.questionTitle', {}, locale)}</label><textarea id="overview-question" maxlength="20000" placeholder="${t('overview.questionPlaceholder', {}, locale)}">${escape(questionDraft)}</textarea>
      <button type="button" class="primary" id="plan-investigation">${t('overview.planInvestigation', {}, locale)}</button>
    </header>
    ${renderGoldenDemoCard({t, locale, starting: demoStarting})}
    <section class="overview-section"><div class="overview-section-heading"><h2>${t('overview.recent', {}, locale)}</h2>${loading ? `<span role="status">${t('overview.loading', {}, locale)}</span>` : ''}</div>${runs}</section>
    <section class="overview-summary" aria-label="${t('overview.summary', {}, locale)}"><article><h2>${t('overview.librarySummary', {}, locale)}</h2><p>${library?.document_count == null ? t('overview.unknownDocuments', {}, locale) : t('overview.documentCount', {count: count(library.document_count, t, locale)}, locale)}</p><p class="overview-muted">${t('overview.indexStatus', {status: count(library?.index_status, t, locale)}, locale)}</p></article>
      <article><h2>${t('overview.reviewSummary', {}, locale)}</h2><p>${overview?.review_summary?.open_run_issue_count == null ? t('overview.unknownOpenIssues', {}, locale) : t('overview.openIssues', {count: count(overview.review_summary.open_run_issue_count, t, locale)}, locale)}</p></article></section>
  </section>`;
}
