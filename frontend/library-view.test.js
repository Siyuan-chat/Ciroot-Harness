import test from 'node:test';
import assert from 'node:assert/strict';
import { visibleLibrary, selectedDocument } from './library-view.js';

test('filtered last document keeps its own identity and original file', () => {
  const items = [
    { document_id: 'first', title: 'A Brief Review', versions: [{ version_id: 'first-version' }] },
    { document_id: 'last', title: 'Tuning Alkaline', versions: [{ version_id: 'last-version' }] },
  ];
  const filtered = visibleLibrary(items, 'all', 'Tuning Alkaline');
  assert.equal(filtered.length, 1);
  assert.equal(selectedDocument(items, filtered[0].document_id)?.versions[0].version_id, 'last-version');
  assert.equal(visibleLibrary(items, 'all', '').length, 2);
  assert.equal(selectedDocument([...items, { document_id: 'page-2' }], 'page-2')?.document_id, 'page-2');
});
