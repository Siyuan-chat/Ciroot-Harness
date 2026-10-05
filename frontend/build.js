import { mkdir, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const here=dirname(fileURLToPath(import.meta.url));
await mkdir(join(here,'dist'),{recursive:true});
await mkdir(join(here,'dist','assets'),{recursive:true});
await copyFile(join(here,'../assets/ciroot-harness-logo.png'),join(here,'dist/assets/ciroot-harness-logo.png'));
for(const file of ['index.html','style.css','app.js','api.js','i18n.js','library-view.js','golden-demo-view.js']) await copyFile(join(here,file),join(here,'dist',file));
for(const [directory,files] of Object.entries({pages:['overview.js','investigation.js','report.js','review.js'],components:['golden-demo-card.js','status-badge.js','evidence-trace.js','evidence-inspector.js','document-inspector.js']})){
  const target=join(here,'dist',directory);
  await mkdir(target,{recursive:true});
  for(const file of files) await copyFile(join(here,directory,file),join(target,file));
}
for(const name of ['spec','runtime','scenario']) await copyFile(join(here,'../src/research_harness/examples/investigation',`synthetic-${name}.json`),join(here,'dist',`synthetic-${name}.json`));
