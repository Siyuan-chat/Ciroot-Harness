import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {renderReviewInbox} from './pages/review.js';
import {renderReportSelection} from './pages/report.js';
import {t} from './i18n.js';

const item={kind:'run_issue',actionable:false,decision_actions:[],run_id:'run-demo',run_status:'partial',outcome:'partial',synthetic:true,issue_index:0,code:'RH_NORMALIZE_XML',status:'open',message:'XML normalization was incomplete',reason:null,document_id:null,source:null,impact:null};

test('review inbox surfaces real run issues as read-only and opens their investigation',()=>{
  const html=renderReviewInbox({items:[item],t,locale:'en'});
  assert.match(html,/RH_NORMALIZE_XML/);
  assert.match(html,/Read-only/);
  assert.match(html,/data-review-open-run="run-demo"/);
  assert.match(html,/decision_actions/);
  assert.match(html,/Open investigation/);
  assert.doesNotMatch(html,/data-review-decision|data-submit-review|decision\s*=/i);
  assert.match(html,/Monitor task reviews are not included here/);
});

test('review inbox keeps unavailable run issue counts unknown and preserves null issue fields',()=>{
  const html=renderReviewInbox({items:[{...item,status:null,message:null,document_id:null,source:null,impact:null}],unavailableRuns:[{run_id:'old-run',run_status:'partial',issue_count:null}],t,locale:'ja'});
  assert.match(html,/読み取り専用/);
  assert.match(html,/old-run/);
  assert.match(html,/問題数は不明/);
  assert.match(html,/不明/);
});

test('Reports & Review selection offers report and inbox views in Chinese English Japanese',()=>{
  const labels={zh:['报告','复核收件箱'],en:['Reports','Review inbox'],ja:['レポート','レビュー受信箱']};
  for(const [locale,expected] of Object.entries(labels)){
    const html=renderReportSelection({runs:[],t,locale,view:'reports'});
    assert.match(html,/data-review-hub="reports"/);
    assert.match(html,/data-review-hub="inbox"/);
    for(const label of expected)assert.ok(html.includes(label));
  }
});

test('app scopes review inbox reads and routes issue opening to Investigation, without decision writes',async()=>{
  const [app,api]=await Promise.all([readFile(new URL('./app.js',import.meta.url),'utf8'),readFile(new URL('./api.js',import.meta.url),'utf8')]);
  assert.match(api,/reviewInbox:\s*\(cursor, requestScope, limit=50\) => request\('\/review-inbox/);
  assert.match(app,/api\.reviewInbox\(null,scope\)/);
  assert.match(app,/data-review-open-run.*openInvestigation/);
  assert.match(app,/data-open-monitor-reviews.*loadPage\('reviews'\)/);
});
