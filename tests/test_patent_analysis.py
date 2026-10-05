import sys
from types import ModuleType

import pytest

from research_harness import patent_analysis as pa


def _publication(publication_id, *, version_id=None, revision_id=None, claims=None, language="en", citations=None, family_ids=None, classifications=None):
    version_id = version_id or f"ver-{publication_id}"
    revision_id = revision_id or f"pr-{publication_id}"
    claims = claims if claims is not None else [
        {"claim_number": 1, "text": "1. An independent claim for an ion conductive polymer.", "language": language, "evidence_id": f"ev-{publication_id}-1"},
        {"claim_number": 2, "text": "2. The polymer according to claim 1, with a specified linker.", "language": language, "evidence_id": f"ev-{publication_id}-2"},
    ]
    evidence = []
    for claim in claims:
        evidence.append({
            "evidence_id": claim["evidence_id"], "publication_id": publication_id,
            "version_id": version_id, "parse_revision_id": revision_id,
            "locator": {"kind": "xml_node", "value": f"/claims/claim[{claim['claim_number']}]"},
            "text": claim["text"],
        })
        claim["source_bindings"] = [{
            "evidence_id": claim["evidence_id"], "publication_id": publication_id,
            "version_id": version_id, "parse_revision_id": revision_id,
            "locator": evidence[-1]["locator"], "quote": claim["text"],
        }]
    return {
        "publication_id": publication_id, "version_id": version_id,
        "parse_revision_id": revision_id, "language": language,
        "family_ids": family_ids if family_ids is not None else ["family-1"],
        "classifications": classifications if classifications is not None else [{"scheme": "IPC", "code": "C08G 73/00"}],
        "citations": citations or [], "source_evidence": evidence, "claims": claims,
    }


class _Graph:
    def __init__(self):
        self._nodes = {}
        self._edges = {}

    def add_node(self, node, **attrs):
        self._nodes.setdefault(node, {}).update(attrs)

    def add_edge(self, source, target, **attrs):
        self._nodes.setdefault(source, {})
        self._nodes.setdefault(target, {})
        self._edges[(source, target)] = attrs

    def has_edge(self, source, target):
        return (source, target) in self._edges

    def __contains__(self, node):
        return node in self._nodes

    def nodes(self, data=False):
        return list(self._nodes.items()) if data else list(self._nodes)

    def edges(self, data=False):
        return [(source, target, attrs) for (source, target), attrs in self._edges.items()] if data else list(self._edges)


def _install_analysis_doubles(monkeypatch):
    monkeypatch.setattr(pa, "_optional_versions", lambda: {
        "networkx": {"available": True, "version": "fixture", "license": "BSD-3-Clause"},
        "scikit-learn": {"available": True, "version": "fixture", "license": "BSD-3-Clause"},
    })
    nx = ModuleType("networkx")
    nx.DiGraph = _Graph
    nx.NetworkXNoCycle = type("NetworkXNoCycle", (Exception,), {})

    def find_cycle(graph):
        state, stack = {}, []

        def visit(node):
            state[node] = 1
            stack.append(node)
            for source, target in graph.edges():
                if source != node:
                    continue
                if state.get(target) == 1:
                    i = stack.index(target)
                    return [(stack[j], stack[j + 1]) for j in range(i, len(stack) - 1)] + [(node, target)]
                if state.get(target, 0) == 0:
                    found = visit(target)
                    if found:
                        return found
            stack.pop()
            state[node] = 2
            return []

        for node in graph.nodes():
            if state.get(node, 0) == 0:
                result = visit(node)
                if result:
                    return result
        raise nx.NetworkXNoCycle("cycle not found")

    nx.find_cycle = find_cycle
    monkeypatch.setitem(sys.modules, "networkx", nx)

    sklearn = ModuleType("sklearn")
    feature = ModuleType("sklearn.feature_extraction")
    text = ModuleType("sklearn.feature_extraction.text")

    class _Matrix:
        def __init__(self, texts):
            self.texts = texts

    class _Vectorizer:
        def __init__(self, **_kwargs):
            pass

        def fit_transform(self, texts):
            return _Matrix(texts)

    text.TfidfVectorizer = _Vectorizer
    metrics = ModuleType("sklearn.metrics")
    pairwise = ModuleType("sklearn.metrics.pairwise")
    pairwise.cosine_similarity = lambda matrix: [
        [1.0 if i == j else (0.9 if left == right else 0.25) for j, right in enumerate(matrix.texts)]
        for i, left in enumerate(matrix.texts)
    ]
    sklearn.feature_extraction = feature
    feature.text = text
    sklearn.metrics = metrics
    metrics.pairwise = pairwise
    for name, module in (("sklearn", sklearn), ("sklearn.feature_extraction", feature), ("sklearn.feature_extraction.text", text), ("sklearn.metrics", metrics), ("sklearn.metrics.pairwise", pairwise)):
        monkeypatch.setitem(sys.modules, name, module)


def test_claim_parsing_source_binding_families_classes_graph_and_same_language(monkeypatch):
    _install_analysis_doubles(monkeypatch)
    first = _publication("WO-A", citations=["WO-B"], family_ids=["F1"], classifications=[{"scheme": "IPC", "code": "C08G 73/00"}])
    second = _publication("WO-B", language="en-US", citations=["WO-A"], family_ids=["F1"], classifications=[{"scheme": "IPC", "code": "C08G 73/00"}])
    korean = _publication("KR-C", language="ko", citations=["WO-A"], family_ids=[], classifications=[])
    result = pa.analyze_patent_publications([first, second, korean])

    assert result["conclusion_status"] == "not_assessed"
    assert len(result["input_publications"]) == 3
    assert result["publication_analyses"][0]["claims"][0]["dependency_status"] == "explicit_independent"
    assert result["publication_analyses"][0]["claims"][1]["depends_on"] == ["1"]
    assert result["publication_analyses"][0]["claims"][1]["source_bindings"][0]["binding_checks"]["parse_revision_id"] is True
    family = result["families"][0]
    assert family["family_id"] == "F1" and family["publication_ids"] == ["WO-A", "WO-B"] and family["publication_count"] == 2
    assert all(member["version_id"] and member["parse_revision_id"] and member["source_bindings"] for member in family["members"])
    classification = result["classification_counts"][0]
    assert (classification["scheme"], classification["code"], classification["publication_count"]) == ("IPC", "C08G 73/00", 2)
    assert all(item["source_bindings"] for item in classification["contributing_publications"])
    assert result["citation_network"]["status"] == "available"
    assert {tuple((e["source_publication_id"], e["cited_publication_id"])) for e in result["citation_network"]["edges"]} == {("WO-A", "WO-B"), ("WO-B", "WO-A"), ("KR-C", "WO-A")}
    assert any(issue["code"] == "citation_network_cycle" for issue in result["issues"])
    assert result["same_language_claim_similarity"]["status"] == "available"
    assert result["same_language_claim_similarity"]["pairs"]
    assert all(edge["source_bindings"] for edge in result["citation_network"]["edges"])
    assert all(pair["language"] == "en" for pair in result["same_language_claim_similarity"]["pairs"])
    assert all(pair["interpretation"].startswith("lexical similarity only") for pair in result["same_language_claim_similarity"]["pairs"])


def test_unknown_missing_and_cyclic_claim_dependencies_are_visible(monkeypatch):
    _install_analysis_doubles(monkeypatch)
    claims = [
        {"claim_number": 1, "text": "1. A material according to claim 2.", "evidence_id": "ev-X-1"},
        {"claim_number": 2, "text": "2. A material according to claim 1 and claim 9.", "evidence_id": "ev-X-2"},
        {"claim_number": 3, "text": "3. A material with an unspecified relation.", "evidence_id": "ev-X-3"},
    ]
    publication = _publication("X", claims=claims)
    result = pa.analyze_patent_publications([publication])
    analysis = result["publication_analyses"][0]
    assert analysis["claim_dependency_cycles"] == [["1", "2"]]
    assert analysis["claims"][2]["dependency_status"] == "unknown"
    codes = {issue["code"] for issue in result["issues"]}
    assert {"claim_dependency_cycle", "missing_claim_dependency", "claim_dependency_unknown"} <= codes


def test_missing_or_duplicate_identities_and_wrong_source_bindings_are_preserved_and_reported(monkeypatch):
    _install_analysis_doubles(monkeypatch)
    first = _publication("DUP")
    wrong = _publication("DUP")
    wrong["claims"][0]["source_bindings"][0]["parse_revision_id"] = "pr-wrong"
    wrong["source_evidence"][0]["parse_revision_id"] = "pr-other"
    missing = _publication("MISSING")
    missing["version_id"] = None
    missing["parse_revision_id"] = None
    result = pa.analyze_patent_publications([first, wrong, missing])
    codes = {issue["code"] for issue in result["issues"]}
    assert {"duplicate_publication_id", "source_binding_mismatch", "claim_source_binding_mismatch", "missing_publication_binding"} <= codes
    assert len(result["input_publications"]) == 3
    assert result["citation_network"]["nodes"] == []


def test_optional_dependency_missing_returns_capability_states(monkeypatch):
    monkeypatch.setattr(pa, "_optional_versions", lambda: {
        "networkx": {"available": False, "version": None, "license": "BSD-3-Clause", "reason": "optional_dependency_missing"},
        "scikit-learn": {"available": False, "version": None, "license": "BSD-3-Clause", "reason": "optional_dependency_missing"},
    })
    result = pa.analyze_patent_publications([_publication("A")])
    assert result["citation_network"]["status"] == "unavailable"
    assert result["same_language_claim_similarity"]["status"] == "unavailable"
    assert {item["dependency"] for item in result["issues"] if item["code"] == "optional_dependency_missing"} == {"networkx", "scikit-learn"}


def test_invalid_container_is_rejected():
    with pytest.raises(ValueError):
        pa.analyze_patent_publications({"publication_id": "not-a-list"})


@pytest.mark.parametrize("text,expected", [
    ("according to claims 1 to 3", ["1", "2", "3"]),
    ("根据权利要求1至3", ["1", "2", "3"]),
    ("請求項１〜３のいずれか", ["1", "2", "3"]),
    ("청구항 제2항 내지 제4항", ["2", "3", "4"]),
])
def test_dependency_parser_reads_only_explicit_supported_language_forms(text, expected):
    assert pa._explicit_dependencies(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("according to claims 1 and 2", ["1", "2"]),
    ("請求項1又は2", ["1", "2"]),
    ("claims 1 to 3 and 5", ["1", "2", "3", "5"]),
])
def test_dependency_parser_reads_complete_lists(text, expected):
    status, refs = pa._parse_dependencies(text)
    assert status == "explicit_references"
    assert refs == expected


def test_incomplete_dependency_list_is_partial_and_claim_numbers_are_normalized():
    assert pa._parse_dependencies("claims 1 and") == ("partial", ["1"])
    assert pa._claim_number({"claim_number": "0"}) is None
    assert pa._claim_number({"claim_number": "01"}) == "1"


def test_fake_claim_text_with_valid_quote_remains_draft_and_is_excluded(monkeypatch):
    _install_analysis_doubles(monkeypatch)
    first = _publication("FAKE-A")
    first["claims"][0]["text"] = "1. A fabricated mass-production claim."
    second = _publication("FAKE-B")
    result = pa.analyze_patent_publications([first, second])
    claim = result["publication_analyses"][0]["claims"][0]
    assert claim["analysis_status"] == "draft"
    assert claim["trusted_structure_eligible"] is False
    assert claim["depends_on"] == []
    assert claim["source_bindings"][0]["binding_checks"]["quote"] is True
    assert claim["source_bindings"][0]["binding_checks"]["claim_text_continuous_unique"] is False
    assert all(not (side["publication_id"] == "FAKE-A" and side["claim_number"] == "1") for pair in result["same_language_claim_similarity"]["pairs"] for side in (pair["left"], pair["right"]))
    assert any(issue["code"] == "claim_source_binding_mismatch" for issue in result["issues"])


def test_nonunique_full_claim_text_hit_is_draft_and_unbound_publication_is_not_aggregated(monkeypatch):
    _install_analysis_doubles(monkeypatch)
    repeated = _publication("REPEAT")
    repeated["source_evidence"][0]["text"] += " duplicate: " + repeated["claims"][0]["text"]
    unbound = _publication("UNBOUND", family_ids=["F"], classifications=[{"scheme": "IPC", "code": "X"}])
    unbound["version_id"] = "ver-UNBOUND"
    unbound["parse_revision_id"] = "pr-UNBOUND"
    for evidence in unbound["source_evidence"]:
        evidence["version_id"] = "wrong-version"
    result = pa.analyze_patent_publications([repeated, unbound])
    claim = result["publication_analyses"][0]["claims"][0]
    assert claim["analysis_status"] == "draft"
    assert claim["source_bindings"][0]["binding_checks"]["claim_text_continuous_unique"] is False
    assert all("UNBOUND" not in family["publication_ids"] for family in result["families"])
    assert all(item["code"] != "X" for item in result["classification_counts"])


def test_unknown_or_mixed_language_is_not_a_similarity_group(monkeypatch):
    _install_analysis_doubles(monkeypatch)
    for language in ("und", "mixed"):
        first = _publication(f"U1-{language}", language=language)
        second = _publication(f"U2-{language}", language=language)
        result = pa.analyze_patent_publications([first, second])
        assert result["same_language_claim_similarity"]["pairs"] == []
