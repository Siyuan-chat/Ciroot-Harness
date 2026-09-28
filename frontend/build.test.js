import test from 'node:test';
import assert from 'node:assert/strict';
import {access, readFile} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {dirname, join, resolve} from 'node:path';

const root=dirname(fileURLToPath(import.meta.url));
const dist=join(root,'dist');

test('static build includes every local module imported by the browser entrypoint',async()=>{
  const build=spawnSync(process.execPath,['build.js'],{cwd:root,encoding:'utf8'});
  assert.equal(build.status,0,build.stderr||build.stdout);
  const entry=await readFile(join(dist,'app.js'),'utf8');
  const modulePaths=new Set(['app.js']);
  for(const match of entry.matchAll(/from\s+['"](\.\/[^'"]+)['"]/g)) modulePaths.add(match[1].slice(2));
  for(const source of [...modulePaths]){
    const contents=await readFile(join(dist,source),'utf8');
    for(const match of contents.matchAll(/from\s+['"](\.\.?\/[^'"]+)['"]/g)){
      const imported=resolve(dirname(join(dist,source)),match[1]);
      assert.ok(imported.startsWith(resolve(dist)+`${process.platform==='win32'?'\\':'/'}`),`${source} imports outside dist: ${match[1]}`);
      const relative=imported.slice(resolve(dist).length+1);
      await access(relative.includes('.')?imported:`${imported}.js`);
    }
  }
  for(const file of ['pages/overview.js','pages/investigation.js','pages/report.js','pages/review.js','components/golden-demo-card.js','components/status-badge.js','components/evidence-trace.js','components/evidence-inspector.js','components/document-inspector.js']) await access(join(dist,file));
});
