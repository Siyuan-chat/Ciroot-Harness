export function visibleLibrary(items, filter, search) {
  const query = search.toLowerCase();
  return items.filter(item => {
    const patent = String(item.kind || item.document_type || item.type || '').toLowerCase().includes('patent');
    const typeMatches = filter === 'all' || (filter === 'patent' ? patent : !patent);
    const text = JSON.stringify([item.title, item.name, item.document_id, item.publication_id]).toLowerCase();
    return typeMatches && (!query || text.includes(query));
  });
}

export function selectedDocument(items, documentId) {
  return items.find(item => item.document_id === documentId);
}
