"""Offline, source-bound structural summaries for patent publications.

This module reports bibliographic structure only. It does not assess legal
scope, novelty, validity, scientific support, or technical merit.
"""
from __future__ import annotations

import copy
import importlib.metadata
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any


_DEPENDENCY_PATTERNS = (
    re.compile(r"(?:claims?|claim\s+no\.?|according\s+to\s+claim)\s*(?:no\.?\s*)?(\d+)(?:\s*(?:to|through|至|到|乃至|から|ないし|내지|〜|～|~|[-–])\s*(?:claim\s*)?(\d+))?", re.IGNORECASE),
    re.compile(r"(?:請求項|权利要求|청구항)\s*(?:(?:第|제)\s*)?(\d+)\s*(?:항)?(?:\s*(?:至|到|乃至|から|ないし|내지|〜|～|~|[-–])\s*(?:(?:第|제)\s*)?(\d+)\s*(?:항)?)?"),
)
_EXPLICIT_INDEPENDENT = re.compile(r"\b(independent\s+claim)\b|独立請求項|独立权利要求|독립항", re.IGNORECASE)


def _issue(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **details}


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _claim_number(claim: dict[str, Any]) -> str | None:
    value = claim.get("claim_number")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    if _nonempty_string(value):
        normalized = unicodedata.normalize("NFKC", value).strip()
        return str(int(normalized)) if normalized.isdigit() and int(normalized) > 0 else None
    text = claim.get("text")
    if isinstance(text, str):
        match = re.match(r"^\s*(\d+)\s*[.、)）:]", unicodedata.normalize("NFKC", text))
        if match:
            return str(int(match.group(1))) if int(match.group(1)) > 0 else None
    return None


def _parse_dependencies(text: str) -> tuple[str, list[str]]:
    """Parse only complete, explicitly supported dependency lists/ranges."""
    normalized = unicodedata.normalize("NFKC", text)
    anchor = r"(?:claims?|claim\s+no\.?|according\s+to\s+claims?|請求項|权利要求|청구항)"
    number = r"(?:第\s*|제\s*)?(\d+)(?:\s*항)?"
    connector = r"(?:,|;|and\b|or\b|又は|または|及び|および|或|和|및|또는)"
    range_word = r"(?:to\b|through\b|至|到|乃至|から|ないし|내지|〜|～|~|[-–])"
    refs: set[str] = set()
    found_marker = False
    partial = False
    pattern = re.compile(rf"{anchor}\s*{number}", re.IGNORECASE)
    for match in pattern.finditer(normalized):
        found_marker = True
        values = [int(match.group(1))]
        cursor = match.end()
        while cursor < len(normalized):
            tail = normalized[cursor:]
            range_match = re.match(rf"\s*{range_word}\s*{anchor}?\s*{number}", tail, re.IGNORECASE)
            list_match = re.match(rf"\s*{connector}\s*{anchor}?\s*{number}", tail, re.IGNORECASE)
            item = range_match or list_match
            if not item:
                if re.match(rf"\s*{connector}\s*$", tail, re.IGNORECASE):
                    partial = True
                break
            values.append(int(item.group(1)))
            cursor += item.end()
            if range_match:
                start, end = values[-2], values[-1]
                if end < start or end - start > 100:
                    partial = True
                else:
                    values[-2:] = list(range(start, end + 1))
        if any(value <= 0 for value in values):
            partial = True
        else:
            refs.update(str(value) for value in values)
    ordered = sorted(refs, key=int)
    return ("partial" if partial else "explicit_references" if found_marker and ordered else "unknown", ordered)


def _explicit_dependencies(text: str) -> list[str]:
    return _parse_dependencies(text)[1]


def _claim_cycles(claim_numbers: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    graph: dict[str, list[str]] = {number: [] for number in claim_numbers}
    for source, target in edges:
        if source in graph and target in graph:
            graph[source].append(target)
    state: dict[str, int] = {}
    stack: list[str] = []
    cycles: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for target in graph[node]:
            if state.get(target, 0) == 0:
                visit(target)
            elif state.get(target) == 1:
                cycle = stack[stack.index(target):]
                rotations = [tuple(cycle[i:] + cycle[:i]) for i in range(len(cycle))]
                cycles.add(min(rotations))
        stack.pop()
        state[node] = 2

    for node in sorted(graph, key=lambda value: int(value)):
        if state.get(node, 0) == 0:
            visit(node)
    return [list(cycle) for cycle in sorted(cycles)]


def _language_key(value: Any) -> str | None:
    if not _nonempty_string(value):
        return None
    language = value.strip().replace("_", "-").split("-", 1)[0].casefold()
    return None if language in {"und", "mul", "zxx", "mixed"} else language


def _optional_versions() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for package, import_name in (("networkx", "networkx"), ("scikit-learn", "sklearn")):
        try:
            module = __import__(import_name)
            version = importlib.metadata.version(package)
            result[package] = {"available": True, "version": version, "license": "BSD-3-Clause"}
            del module
        except ImportError:
            result[package] = {"available": False, "version": None, "license": "BSD-3-Clause", "reason": "optional_dependency_missing"}
        except importlib.metadata.PackageNotFoundError:
            result[package] = {"available": False, "version": None, "license": "BSD-3-Clause", "reason": "optional_dependency_missing"}
        except Exception:
            result[package] = {"available": False, "version": None, "license": "BSD-3-Clause", "reason": "optional_dependency_import_failed"}
    return result


def analyze_patent_publications(publications: list[dict[str, Any]]) -> dict[str, Any]:
    """Return traceable claim/family/classification/citation/text summaries.

    Expected publication fields include ``publication_id``, ``version_id``,
    ``parse_revision_id``, ``source_evidence``, ``claims``, ``family_ids``,
    ``classifications``, ``citations`` and a language tag. Missing or repeated
    identities remain in the result and are accompanied by diagnostics.
    """
    if not isinstance(publications, list) or not all(isinstance(item, dict) for item in publications):
        raise ValueError("publications must be a list of objects")

    inputs = copy.deepcopy(publications)
    issues: list[dict[str, Any]] = []
    capabilities = _optional_versions()
    seen_publication_ids: Counter[str] = Counter(
        item["publication_id"].strip() for item in inputs if _nonempty_string(item.get("publication_id"))
    )
    evidence_by_id: dict[str, tuple[int, dict[str, Any]]] = {}
    evidence_counts: Counter[str] = Counter()
    for pub_index, publication in enumerate(inputs):
        pub_id = publication.get("publication_id")
        if not _nonempty_string(pub_id):
            issues.append(_issue("missing_publication_id", "publication identity is missing", publication_index=pub_index))
        elif seen_publication_ids[pub_id.strip()] > 1:
            issues.append(_issue("duplicate_publication_id", "publication identity is repeated; graph ownership is ambiguous", publication_id=pub_id, publication_index=pub_index))
        for field in ("version_id", "parse_revision_id"):
            if not _nonempty_string(publication.get(field)):
                issues.append(_issue("missing_publication_binding", f"{field} is missing", publication_id=pub_id, publication_index=pub_index, field=field))
        source_evidence = publication.get("source_evidence", [])
        if not isinstance(source_evidence, list):
            issues.append(_issue("invalid_source_evidence", "source_evidence must be a list", publication_id=pub_id))
            continue
        for evidence_index, evidence in enumerate(source_evidence):
            if not isinstance(evidence, dict):
                issues.append(_issue("invalid_source_evidence", "source evidence entry must be an object", publication_id=pub_id, evidence_index=evidence_index))
                continue
            evidence_id = evidence.get("evidence_id")
            if not _nonempty_string(evidence_id):
                issues.append(_issue("missing_evidence_id", "source evidence identity is missing", publication_id=pub_id, evidence_index=evidence_index))
                continue
            evidence_counts[evidence_id] += 1
            if evidence_id in evidence_by_id:
                issues.append(_issue("duplicate_evidence_id", "source evidence identity is repeated", evidence_id=evidence_id, publication_id=pub_id))
            else:
                evidence_by_id[evidence_id] = (pub_index, evidence)

    family_members: dict[str, dict[tuple[str, str, str], dict[str, Any]]] = defaultdict(dict)
    classification_members: dict[tuple[str, str], dict[tuple[str, str, str], dict[str, Any]]] = defaultdict(dict)
    citation_edges: list[tuple[str, str, int, list[dict[str, Any]]]] = []
    all_claim_texts: list[dict[str, Any]] = []
    publication_analyses: list[dict[str, Any]] = []

    for pub_index, publication in enumerate(inputs):
        pub_id = publication.get("publication_id")
        version_id = publication.get("version_id")
        revision_id = publication.get("parse_revision_id")
        pub_issues: list[dict[str, Any]] = []
        valid_pub_identity = (_nonempty_string(pub_id) and seen_publication_ids[pub_id.strip()] == 1)
        valid_pub_source = valid_pub_identity and _nonempty_string(version_id) and _nonempty_string(revision_id)
        bindings: list[dict[str, Any]] = []
        for evidence in publication.get("source_evidence", []) if isinstance(publication.get("source_evidence", []), list) else []:
            if not isinstance(evidence, dict):
                continue
            checks = {
                "publication_id": evidence.get("publication_id") == pub_id,
                "version_id": evidence.get("version_id") == version_id,
                "parse_revision_id": evidence.get("parse_revision_id") == revision_id,
                "locator": bool(evidence.get("locator")),
                "text": isinstance(evidence.get("text"), str) and bool(evidence.get("text")),
            }
            if not _nonempty_string(revision_id):
                checks["parse_revision_id"] = False
            if not all(checks.values()):
                issue = _issue("source_binding_mismatch", "evidence does not explicitly bind to this publication version and parse revision", publication_id=pub_id, evidence_id=evidence.get("evidence_id"), checks=checks)
                pub_issues.append(issue); issues.append(issue)
            bindings.append({"evidence_id": evidence.get("evidence_id"), "publication_id": evidence.get("publication_id"), "version_id": evidence.get("version_id"), "parse_revision_id": evidence.get("parse_revision_id"), "locator": copy.deepcopy(evidence.get("locator")), "binding_checks": checks})

        trusted_bindings = [binding for binding in bindings if all(binding["binding_checks"].values()) and evidence_counts.get(str(binding.get("evidence_id")), 0) == 1]
        valid_pub_source = bool(valid_pub_source and trusted_bindings)
        source_identity = {"publication_id": pub_id.strip() if _nonempty_string(pub_id) else None, "version_id": version_id, "parse_revision_id": revision_id, "source_bindings": copy.deepcopy(trusted_bindings)}

        family_ids = publication.get("family_ids", [])
        if isinstance(family_ids, list):
            for family_id in family_ids:
                if _nonempty_string(family_id):
                    if valid_pub_source:
                        family_members[family_id][(pub_id.strip(), str(version_id), str(revision_id))] = source_identity
                else:
                    issue = _issue("invalid_family_id", "family identity is missing or invalid", publication_id=pub_id)
                    pub_issues.append(issue); issues.append(issue)
        elif family_ids is not None:
            issue = _issue("invalid_family_id", "family_ids must be a list", publication_id=pub_id)
            pub_issues.append(issue); issues.append(issue)

        classes = publication.get("classifications", [])
        if not isinstance(classes, list):
            issue = _issue("invalid_classifications", "classifications must be a list", publication_id=pub_id)
            pub_issues.append(issue); issues.append(issue)
            classes = []
        publication_classifications: set[tuple[str, str]] = set()
        for classification in classes:
            if not isinstance(classification, dict) or not _nonempty_string(classification.get("scheme")) or not _nonempty_string(classification.get("code")):
                issue = _issue("invalid_classification", "classification requires explicit scheme and code", publication_id=pub_id)
                pub_issues.append(issue); issues.append(issue)
                continue
            publication_classifications.add((classification["scheme"].strip().upper(), classification["code"].strip()))
        if valid_pub_source:
            for classification_key in publication_classifications:
                classification_members[classification_key][(pub_id.strip(), str(version_id), str(revision_id))] = source_identity

        citations = publication.get("citations", [])
        if not isinstance(citations, list):
            issue = _issue("invalid_citations", "citations must be a list", publication_id=pub_id)
            pub_issues.append(issue); issues.append(issue)
            citations = []
        for target in citations:
            if not _nonempty_string(target):
                issue = _issue("invalid_citation_target", "citation target identity is missing", publication_id=pub_id)
                pub_issues.append(issue); issues.append(issue)
            elif valid_pub_source:
                citation_edges.append((pub_id.strip(), target.strip(), pub_index, copy.deepcopy(trusted_bindings)))

        raw_claims = publication.get("claims", [])
        if not isinstance(raw_claims, list):
            issue = _issue("invalid_claims", "claims must be a list", publication_id=pub_id)
            pub_issues.append(issue); issues.append(issue)
            raw_claims = []
        parsed_claims: list[dict[str, Any]] = []
        numbers_seen: Counter[str] = Counter()
        for claim_index, claim in enumerate(raw_claims):
            if not isinstance(claim, dict):
                issue = _issue("invalid_claim", "claim must be an object", publication_id=pub_id, claim_index=claim_index)
                pub_issues.append(issue); issues.append(issue)
                continue
            number = _claim_number(claim)
            if number is None:
                issue = _issue("missing_claim_number", "claim number is not explicitly supplied or readable from its leading label", publication_id=pub_id, claim_index=claim_index)
                pub_issues.append(issue); issues.append(issue)
            else:
                numbers_seen[number] += 1
                if numbers_seen[number] > 1:
                    issue = _issue("duplicate_claim_number", "claim number is repeated within a publication", publication_id=pub_id, claim_number=number)
                    pub_issues.append(issue); issues.append(issue)
            text = claim.get("text")
            if not isinstance(text, str) or not text.strip():
                issue = _issue("missing_claim_text", "claim text is missing", publication_id=pub_id, claim_number=number)
                pub_issues.append(issue); issues.append(issue)
                text = ""
            claim_language = _language_key(claim.get("language", publication.get("language")))
            dependency_status, refs = _parse_dependencies(text)
            if dependency_status == "explicit_references":
                pass
            elif dependency_status == "partial":
                issue = _issue("claim_dependency_partial", "dependency list contains an unsupported or incomplete expression; parsed subset is diagnostic only", publication_id=pub_id, claim_number=number, parsed_references=refs)
                pub_issues.append(issue); issues.append(issue)
                refs = []
            elif _EXPLICIT_INDEPENDENT.search(unicodedata.normalize("NFKC", text)):
                dependency_status = "explicit_independent"
            else:
                dependency_status = "unknown"
                issue = _issue("claim_dependency_unknown", "no explicit dependency or independent-claim marker was parsed; no relation is inferred", publication_id=pub_id, claim_number=number)
                pub_issues.append(issue); issues.append(issue)
            source_refs = claim.get("source_bindings", [])
            if not isinstance(source_refs, list) or not source_refs:
                issue = _issue("claim_source_missing", "claim has no explicit source binding", publication_id=pub_id, claim_number=number)
                pub_issues.append(issue); issues.append(issue)
                source_refs = []
            claim_bindings: list[dict[str, Any]] = []
            for source_ref in source_refs:
                if not isinstance(source_ref, dict):
                    issue = _issue("invalid_claim_source", "claim source binding must be an object", publication_id=pub_id, claim_number=number)
                    pub_issues.append(issue); issues.append(issue)
                    continue
                evidence_id = source_ref.get("evidence_id")
                found = evidence_by_id.get(evidence_id) if isinstance(evidence_id, str) else None
                evidence = found[1] if found and found[0] == pub_index else None
                checks = {
                    "evidence_identity": evidence is not None and evidence_counts[evidence_id] == 1,
                    "publication_id": source_ref.get("publication_id") == pub_id and evidence is not None and evidence.get("publication_id") == pub_id,
                    "version_id": source_ref.get("version_id") == version_id and evidence is not None and evidence.get("version_id") == version_id,
                    "parse_revision_id": source_ref.get("parse_revision_id") == revision_id and _nonempty_string(revision_id) and evidence is not None and evidence.get("parse_revision_id") == revision_id,
                    "locator": evidence is not None and source_ref.get("locator") == evidence.get("locator") and bool(evidence.get("locator")),
                    "quote": evidence is not None and isinstance(source_ref.get("quote"), str) and bool(source_ref.get("quote")) and source_ref.get("quote") in str(evidence.get("text", "")),
                    "claim_text_continuous_unique": evidence is not None and isinstance(text, str) and bool(text) and str(evidence.get("text", "")).count(text) == 1,
                }
                if not all(checks.values()):
                    issue = _issue("claim_source_binding_mismatch", "claim source must resolve to the exact publication/version/revision/locator, quote and unique continuous full claim text", publication_id=pub_id, claim_number=number, evidence_id=evidence_id, checks=checks)
                    pub_issues.append(issue); issues.append(issue)
                claim_bindings.append({"evidence_id": evidence_id, "publication_id": source_ref.get("publication_id"), "version_id": source_ref.get("version_id"), "parse_revision_id": source_ref.get("parse_revision_id"), "locator": copy.deepcopy(source_ref.get("locator")), "quote": source_ref.get("quote"), "binding_checks": checks})
            trusted_claim_binding = bool(claim_bindings) and all(all(check.get(k, False) for k in ("evidence_identity", "publication_id", "version_id", "parse_revision_id", "locator", "quote", "claim_text_continuous_unique")) for check in (ref["binding_checks"] for ref in claim_bindings))
            parsed = {"claim_number": number, "text": text, "language": claim_language, "dependency_status": dependency_status, "depends_on": refs if trusted_claim_binding else [], "source_bindings": claim_bindings, "analysis_status": "eligible" if trusted_claim_binding and number else "draft", "trusted_structure_eligible": bool(trusted_claim_binding and number), "claim_index": claim_index}
            if not trusted_claim_binding:
                parsed["dependency_status"] = "unknown"
            parsed_claims.append(parsed)
            if text:
                all_claim_texts.append({"publication_index": pub_index, "publication_id": pub_id, "version_id": version_id, "parse_revision_id": revision_id, "claim_number": number, "language": claim_language, "text": text, "source_bindings": claim_bindings, "source_binding_valid": trusted_claim_binding})

        available_numbers = {claim["claim_number"] for claim in parsed_claims if claim["claim_number"] is not None}
        dependency_edges: list[tuple[str, str]] = []
        for claim in parsed_claims:
            for dependency in claim["depends_on"]:
                if dependency not in available_numbers:
                    issue = _issue("missing_claim_dependency", "explicit dependency points to a claim number absent from this publication", publication_id=pub_id, claim_number=claim["claim_number"], missing_claim_number=dependency)
                    pub_issues.append(issue); issues.append(issue)
                elif claim["claim_number"] is not None:
                    dependency_edges.append((claim["claim_number"], dependency))
        cycles = _claim_cycles(sorted(available_numbers, key=lambda value: int(value)), dependency_edges)
        for cycle in cycles:
            issue = _issue("claim_dependency_cycle", "explicit claim dependency relations contain a cycle", publication_id=pub_id, cycle=cycle)
            pub_issues.append(issue); issues.append(issue)
        publication_analyses.append({"publication_index": pub_index, "publication_id": pub_id, "version_id": version_id, "parse_revision_id": revision_id, "source_bindings": bindings, "claims": parsed_claims, "claim_dependency_edges": [{"claim_number": source, "depends_on": target} for source, target in dependency_edges], "claim_dependency_cycles": cycles, "issues": pub_issues})

    valid_nodes = {
        item["publication_id"].strip(): item
        for item in inputs
        if _nonempty_string(item.get("publication_id")) and seen_publication_ids[item["publication_id"].strip()] == 1 and _nonempty_string(item.get("version_id")) and _nonempty_string(item.get("parse_revision_id")) and any(all(binding["binding_checks"].values()) for binding in next((analysis["source_bindings"] for analysis in publication_analyses if analysis["publication_id"] == item["publication_id"]), []))
    }
    graph_status = "unavailable"
    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []
    if capabilities["networkx"]["available"]:
        try:
            import networkx as nx

            graph = nx.DiGraph()
            for pub_id, publication in sorted(valid_nodes.items()):
                analysis = next(item for item in publication_analyses if item["publication_id"] == pub_id)
                source_bindings = [binding for binding in analysis["source_bindings"] if all(binding["binding_checks"].values())]
                graph.add_node(pub_id, version_id=publication.get("version_id"), parse_revision_id=publication.get("parse_revision_id"), family_ids=copy.deepcopy(publication.get("family_ids", [])), source_bindings=copy.deepcopy(source_bindings))
            for source, target, pub_index, source_bindings in citation_edges:
                if target not in graph:
                    graph.add_node(target, unresolved=True, source_bindings=[])
                    issue = _issue("unresolved_citation_target", "citation target is outside the supplied publication set", publication_id=source, cited_publication_id=target, publication_index=pub_index)
                    issues.append(issue)
                if graph.has_edge(source, target):
                    issue = _issue("duplicate_citation", "citation edge is repeated", publication_id=source, cited_publication_id=target)
                    issues.append(issue)
                else:
                    target_bindings = [binding for binding in next((analysis["source_bindings"] for analysis in publication_analyses if analysis["publication_id"] == target), []) if all(binding["binding_checks"].values())]
                    graph.add_edge(source, target, relation="cites", source_bindings=copy.deepcopy(source_bindings), target_source_bindings=copy.deepcopy(target_bindings))
            graph_nodes = [{"publication_id": str(node), **copy.deepcopy(attrs)} for node, attrs in sorted(graph.nodes(data=True), key=lambda row: str(row[0]))]
            graph_edges = [{"source_publication_id": str(source), "cited_publication_id": str(target), **copy.deepcopy(attrs)} for source, target, attrs in sorted(graph.edges(data=True), key=lambda row: (str(row[0]), str(row[1])))]
            try:
                cycle = nx.find_cycle(graph)
            except nx.NetworkXNoCycle:
                cycle = []
            if cycle:
                issues.append(_issue("citation_network_cycle", "citation graph contains a directed cycle; this is a structural observation only", cycle=[[str(source), str(target)] for source, target in cycle]))
            graph_status = "available"
        except ImportError:
            capabilities["networkx"] = {**capabilities["networkx"], "available": False, "reason": "optional_dependency_import_failed"}

    similarities: list[dict[str, Any]] = []
    similarity_status = "unavailable"
    if capabilities["scikit-learn"]["available"]:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity

            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in all_claim_texts:
                if row["language"]:
                    groups[row["language"]].append(row)
            for language, rows in sorted(groups.items()):
                eligible = [row for row in rows if row["publication_index"] < len(publication_analyses) and row["source_binding_valid"] and publication_analyses[row["publication_index"]]["publication_id"] and seen_publication_ids.get(str(row["publication_id"]).strip(), 0) == 1]
                # Similarity is a lexical diagnostic over exact supplied claim text, not support.
                if len(eligible) < 2:
                    continue
                try:
                    matrix = TfidfVectorizer(analyzer="char", ngram_range=(2, 4), lowercase=False).fit_transform([row["text"] for row in eligible])
                except ValueError:
                    continue
                scores = cosine_similarity(matrix)
                for i, left in enumerate(eligible):
                    for j in range(i + 1, len(eligible)):
                        right = eligible[j]
                        if left["publication_id"] == right["publication_id"]:
                            continue
                        try:
                            score = float(scores[i, j])
                        except TypeError:
                            score = float(scores[i][j])
                        if score > 0:
                            similarities.append({"left": {k: left[k] for k in ("publication_id", "version_id", "parse_revision_id", "claim_number")}, "right": {k: right[k] for k in ("publication_id", "version_id", "parse_revision_id", "claim_number")}, "language": language, "method": "tfidf_character_ngram_cosine", "score": score, "interpretation": "lexical similarity only; not legal, scientific, or evidentiary support"})
            similarity_status = "available"
        except ImportError:
            capabilities["scikit-learn"] = {**capabilities["scikit-learn"], "available": False, "reason": "optional_dependency_import_failed"}

    for package, capability in capabilities.items():
        if not capability["available"]:
            issues.append(_issue("optional_dependency_missing", f"optional dependency {package} is unavailable", dependency=package, reason=capability.get("reason")))

    return {
        "analysis_kind": "patent_structural_summary",
        "conclusion_status": "not_assessed",
        "limitations": ["No legal or scientific support conclusion is produced.", "Only explicit claim dependency markers are parsed; ambiguous relations remain unknown.", "Text similarity is same-language lexical similarity only."],
        "capabilities": {"networkx": {**capabilities["networkx"], "status": graph_status}, "scikit-learn": {**capabilities["scikit-learn"], "status": similarity_status}},
        "input_publications": inputs,
        "publication_analyses": publication_analyses,
        "families": [{"family_id": family_id, "members": [members[key] for key in sorted(members)], "publication_ids": sorted({key[0] for key in members}), "publication_count": len(members)} for family_id, members in sorted(family_members.items())],
        "classification_counts": [{"scheme": scheme, "code": code, "contributing_publications": [members[key] for key in sorted(members)], "publication_count": len(members)} for (scheme, code), members in sorted(classification_members.items())],
        "citation_network": {"status": graph_status, "directed": True, "nodes": graph_nodes, "edges": graph_edges},
        "same_language_claim_similarity": {"status": similarity_status, "method": "tfidf_character_ngram_cosine", "pairs": similarities},
        "issues": issues,
    }
