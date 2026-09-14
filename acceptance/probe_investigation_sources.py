"""Independent synthetic source-boundary probes; no external requests."""
import argparse, base64, copy, io, json, sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source-root',required=True,type=Path);p.add_argument('--checkpoint',required=True);p.add_argument('--output',required=True,type=Path)
a=p.parse_args();sys.path.insert(0,str(a.source_root.resolve()/'src'))
from research_harness.investigation_sources import normalize, policy_allows
from reportlab.pdfgen import canvas
checks=[]
def check(name,fn):
 try:detail=fn();checks.append({'id':name,'status':'passed','detail':detail})
 except Exception as e:checks.append({'id':name,'status':'failed','type':type(e).__name__,'detail':str(e)[:900]})
def chunks(x):return x if isinstance(x,list) else x.get('chunks',[x])
def txt(e):return e.get('text',e.get('quote',''))
def pdf():
 b=io.BytesIO();c=canvas.Canvas(b);c.drawString(50,700,'SYNTHETIC MERIDIAN_PDF_PAGE_ONE_8642');c.showPage();c.drawString(50,700,'SYNTHETIC MERIDIAN_PDF_PAGE_TWO_8642');c.save()
 es=chunks(normalize({'source':'synthetic-paper','document_id':'ind-pdf','version':'v1','content_type':'application/pdf','base64_bytes':base64.b64encode(b.getvalue()).decode()}))
 assert any('MERIDIAN_PDF_PAGE_ONE_8642' in txt(e) for e in es)
 two=[e for e in es if 'MERIDIAN_PDF_PAGE_TWO_8642' in txt(e)];assert two
 assert any('2' in str(e['locator'].get('value',e['locator'].get('page',''))) for e in two),'Physical page two was not retained'
 return {'chunks':len(es),'locators':[e['locator'] for e in es]}
def xml():
 raw='<patent><claims><claim id="c8642">SYNTHETIC XML_CLAIM_8642 indigo separator.</claim></claims><description><p id="p8643">SYNTHETIC XML_DESCRIPTION_8643.</p></description></patent>'
 es=chunks(normalize({'source':'synthetic-patent','document_id':'ind-xml','version':'v1','content_type':'application/xml','text':raw}))
 assert any('XML_CLAIM_8642' in txt(e) and 'c8642' in str(e['locator']) for e in es),'Claim location lost'
 assert any('XML_DESCRIPTION_8643' in txt(e) and 'p8643' in str(e['locator']) for e in es),'Description location lost'
 return {'locators':[e['locator'] for e in es]}
def malformed():
 for kind,raw in [('application/xml','<patent><claim>broken'),('application/pdf','NOT_A_PDF_8642')]:
  try:normalize({'source':'synthetic-paper','document_id':'broken','version':'v1','content_type':kind,'text':raw})
  except Exception as e:
   assert getattr(e,'code','').startswith('RH_'), 'Malformed source needs structured error'
  else:raise AssertionError('Malformed '+kind+' accepted as full text')
 return 'Both malformed formats rejected'
def versions():
 d={'source':'synthetic-paper','document_id':'ind-version','version':'v1','text':'SYNTHETIC identical wording across two source versions.'}
 one=chunks(normalize(d));same=chunks(normalize(copy.deepcopy(d)));two=chunks(normalize(dict(d,version='v2')))
 assert [e['evidence_id'] for e in one]==[e['evidence_id'] for e in same]
 assert not ({e['evidence_id'] for e in one}&{e['evidence_id'] for e in two}),'New version reused old evidence identity'
 assert all(e.get('version_id',e.get('document_version'))=='v1' for e in one)
 left=chunks(normalize(dict(d,document_id='ab',version='c')))
 right=chunks(normalize(dict(d,document_id='a',version='bc')))
 assert left[0]['evidence_id'] != right[0]['evidence_id'], 'Ambiguous document/version concatenation collided'
 return 'Idempotent within version, distinct across source versions and document identity tuples'
def policy():
 item={'visibility':'confidential','company_id':'meridian','text':'PRIVATE_MERIDIAN_8642'}
 rt={'mode':'host','data_mode':'synthetic','model_id':'approved-offline','data_policy':{'company_id':'meridian','allowed_models':['approved-offline'],'allow_query_egress':False}}
 assert policy_allows(item,rt)
 assert not policy_allows(item,rt,query=True)
 assert not policy_allows(dict(item,company_id='another-company'),rt)
 assert not policy_allows(item,dict(rt,model_id='unapproved'))
 assert not policy_allows(item,{})
 return 'Model and query permissions remain independent'
for name,fn in [('F08-PDF-physical-pages',pdf),('F08-XML-locators',xml),('F05-malformed-body',malformed),('F09-evidence-version',versions),('M01-policy-boundary',policy)]:check(name,fn)
r={'checkpoint':a.checkpoint,'synthetic':True,'scope':'Source module checks; integration acceptance remains separate','checks':checks};a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if all(x['status']=='passed' for x in checks) else 1)
