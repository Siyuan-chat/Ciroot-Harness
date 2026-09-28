import test from 'node:test';
import assert from 'node:assert/strict';
import {access,readFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {dirname,join} from 'node:path';

const here=dirname(fileURLToPath(import.meta.url));
test('packaged frontend contains the Overview and Investigation ES modules and imports resolve to files',async()=>{
  const built=spawnSync(process.execPath,['build.js'],{cwd:here,encoding:'utf8'});
  assert.equal(built.status,0,built.stderr||built.stdout);
  for(const path of ['pages/overview.js','pages/investigation.js','components/status-badge.js','components/golden-demo-card.js']){
    await access(join(here,'dist',path));
    const content=await readFile(join(here,'dist',path),'utf8');
    if(path==='pages/overview.js'){
      assert.match(content,/\.\.\/components\/golden-demo-card\.js/);
      assert.match(content,/\.\.\/components\/status-badge\.js/);
    }
    if(path==='pages/investigation.js')assert.match(content,/\.\.\/components\/status-badge\.js/);
  }
});
