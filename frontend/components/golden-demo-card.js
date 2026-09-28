export function renderGoldenDemoCard({t, locale, starting = false, compact = false}) {
  return `<section class="overview-demo ${compact ? 'overview-demo-compact' : ''}" aria-labelledby="golden-demo-title">
    <div><p class="overview-eyebrow">${t('demo.offline', {}, locale)} · ${t('demo.synthetic', {}, locale)} · ${t('demo.noApiKey', {}, locale)}</p>
      <h2 id="golden-demo-title">${t('demo.title', {}, locale)}</h2><p>${t('demo.description', {}, locale)}</p></div>
    <button type="button" class="primary overview-demo-action" data-golden-demo ${starting ? 'disabled aria-disabled="true"' : ''}>${starting ? t('demo.starting', {}, locale) : t(compact ? 'demo.tryShort' : 'demo.try', {}, locale)}</button>
  </section>`;
}
