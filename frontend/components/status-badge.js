const states = {
  completed: ['✓', 'status.completed'],
  complete: ['✓', 'status.completed'],
  verified: ['✓', 'status.verified'],
  open: ['!', 'status.open'],
  partial: ['◐', 'status.partial'],
  running: ['↻', 'status.running'],
  needs_review: ['!', 'status.needsReview'],
  failed: ['×', 'status.failed'],
  unsupported: ['–', 'status.unsupported'],
  stopped: ['■', 'status.stopped'],
  waiting: ['…', 'status.waiting'],
  waiting_credentials: ['…', 'status.waiting'],
  policy_blocked: ['!', 'status.policyBlocked'],
  budget_exhausted: ['!', 'status.budgetExhausted'],
};

export function renderStatusBadge(status, t, locale) {
  const known = Object.hasOwn(states, status);
  const [icon, key] = known ? states[status] : ['·', 'status.unknown'];
  const value = key === 'status.unknown' ? t(key, {status: status || ''}, locale) : t(key, {}, locale);
  const label = String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  return `<span class="status-badge status-${known ? status : 'unknown'}"><span aria-hidden="true">${icon}</span> ${label}</span>`;
}
