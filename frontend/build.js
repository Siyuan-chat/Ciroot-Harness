import { mkdir, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const here=dirname(fileURLToPath(import.meta.url));
await mkdir(join(here,'dist'),{recursive:true});
await mkdir(join(here,'dist','assets'),{recursive:true});
await copyFile(join(here,'../assets/ciroot-harness-logo.png'),join(here,'dist/assets/ciroot-harness-logo.png'));
for(const file of ['index.html','style.css','app.js','api.js','i18n.js','library-view.js','golden-demo-view.js']) await copyFile(join(here,file),join(here,'dist',file));
for (const [source, target] of [['pages/overview.js','pages/overview.js'],['pages/investigation.js','pages/investigation.js'],['components/status-badge.js','components/status-badge.js'],['components/golden-demo-card.js','components/golden-demo-card.js']]) {
  await mkdir(join(here,'dist',target.split('/').slice(0,-1).join('/')),{recursive:true});
  await copyFile(join(here,source),join(here,'dist',target));
}
for(const name of ['spec','runtime','scenario']) await copyFile(join(here,'../src/research_harness/examples/investigation',`synthetic-${name}.json`),join(here,'dist',`synthetic-${name}.json`));
