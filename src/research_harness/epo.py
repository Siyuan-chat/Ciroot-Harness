"""OPS protocol parsing and a small credential-free request client."""
from __future__ import annotations

import json
import os
import time
from xml.etree import ElementTree as ET

from .investigation_sources import SourceError

BASE = "https://ops.epo.org"


def _epodoc(publication):
    return publication["country"]+publication["publication_number"]+"."+publication["kind"]


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]


def _root(body):
    try:
        return ET.fromstring(body)
    except ET.ParseError as exc:
        raise SourceError("RH_SOURCE_INVALID_RESPONSE", "OPS returned invalid XML") from exc


def _xpath(root, node, parents):
    segments=[]
    current=node
    while current is not None:
        parent=parents.get(current)
        siblings=[x for x in parent if _tag(x)==_tag(current)] if parent is not None else [current]
        segments.append(f"{_tag(current)}[{siblings.index(current)+1}]")
        current=parent
    return "/"+"/".join(reversed(segments))


def _publication(element):
    country = element.get("country")
    number = element.get("doc-number")
    kind = element.get("kind")
    if not (country and number):
        doc = next((x for x in element.iter() if _tag(x) == "document-id" and (x.get("document-id-type") == "docdb" or element.get("data-format") == "docdb")), None)
        if doc is not None:
            fields = {_tag(x): (x.text or "").strip() for x in doc}
            country, number, kind = fields.get("country"), fields.get("doc-number"), fields.get("kind")
    if not (country and number and kind):
        return None
    identity = country + number + kind
    return {"document_id": identity, "source_id": identity, "publication_id": identity,
            "country": country, "publication_number": number, "kind": kind,
            "version": "epo-" + identity, "source": "epo"}


def parse_search(body, start, page_size):
    root = _root(body)
    search = next((x for x in root.iter() if _tag(x) == "biblio-search"), None)
    if search is None:
        raise SourceError("RH_SOURCE_INVALID_RESPONSE", "OPS search envelope is missing")
    try:
        total = int(search.get("total-result-count", "0"))
    except ValueError as exc:
        raise SourceError("RH_SOURCE_INVALID_RESPONSE", "OPS result count is invalid") from exc
    candidates = []
    for element in search.iter():
        if _tag(element) != "exchange-document":
            continue
        publication = _publication(element)
        if publication:
            title = next((" ".join(" ".join(x.itertext()).split()) for x in element.iter() if _tag(x) == "invention-title"), None)
            if title: publication["title"] = title
            if element.get("family-id"): publication["source_family_id"] = element.get("family-id")
            candidates.append(publication)
    next_start = start + page_size if start + page_size <= total else None
    return {"candidates": candidates, "next_cursor": str(next_start) if next_start else None,
            "complete": next_start is None, "total": total}


def parse_family(body):
    root = _root(body)
    family = next((x for x in root.iter() if _tag(x) == "patent-family"), None)
    if family is None:
        raise SourceError("RH_SOURCE_INVALID_RESPONSE", "OPS family envelope is missing")
    members = []
    for member in family:
        if _tag(member) != "family-member":
            continue
        for reference in member.iter():
            if _tag(reference) == "publication-reference":
                publication = _publication(reference)
                if publication:
                    members.append(publication)
    return {"family_type": "inpadoc_extended", "members": list({x["publication_id"]: x for x in members}.values()),
            "truncated": family.get("truncatedFamily") == "true"}


def parse_availability(body, publication):
    root=_root(body)
    versions={item["publication_id"] for element in root.iter() if _tag(element)=="publication-reference" if (item:=_publication(element))}
    if publication["publication_id"] not in versions:
        raise SourceError("RH_SOURCE_VERSION_UNVERIFIED","OPS fulltext inquiry does not identify the selected publication")
    sections={x.get("desc") for x in root.iter() if _tag(x)=="fulltext-instance"}
    return {"publication_id":publication["publication_id"],"sections":sorted(x for x in sections if x in {"claims","description"})}


def parse_section(body, section, publication):
    root = _root(body)
    identity_seen=False
    for node in root.iter():
        if _tag(node) == "fulltext-document":
            country, number, kind = node.get("country"), node.get("doc-number"), node.get("kind")
            found=country+number+kind if country and number and kind else None
            if found is None:
                found=next((item["publication_id"] for ref in node.iter() if _tag(ref)=="publication-reference" if (item:=_publication(ref))),None)
            if found:
                identity_seen=True
                if found != publication:
                    raise SourceError("RH_SOURCE_VERSION_MISMATCH", "OPS fulltext belongs to another publication")
    if not identity_seen:
        raise SourceError("RH_SOURCE_VERSION_UNVERIFIED", "OPS fulltext publication identity is absent")
    containers = [x for x in root.iter() if _tag(x) == section]
    if not containers:
        raise SourceError("RH_FULLTEXT_GAP", "OPS section is absent")
    facts = []
    parents={child:parent for parent in root.iter() for child in parent}
    table_gap=any(_tag(node)=="table" for node in root.iter())
    for container in containers:
        language = container.get("lang") or container.get("language")
        wanted={"claim"} if section=="claims" else {"p","paragraph"}
        for node in container.iter():
            if _tag(node) not in wanted or any(_tag(parent)=="table" for parent in _ancestors(node,parents)):
                continue
            text = " ".join(" ".join(node.itertext()).split())
            if not text:
                continue
            identifier=node.get("id") or node.get("num")
            locator={"kind":"epo_xml_id","value":section+":"+identifier} if identifier else {"kind":"epo_xpath","value":_xpath(root,node,parents)}
            explicit_example=section=="description" and any(_tag(parent) in {"example","examples","embodiment"} for parent in _ancestors(node,parents))
            facts.append({"text": text, "locator": locator,
                          "section": "example" if explicit_example else section, "language": language,
                          "publication_id": publication, "table_gap": table_gap})
    if not facts:
        raise SourceError("RH_FULLTEXT_GAP", "OPS section has no extractable text")
    return facts


def _ancestors(node, parents):
    current=parents.get(node)
    while current is not None:
        yield current
        current=parents.get(current)


class EpoClient:
    """The caller's request function owns durable budget reservation and byte accounting."""

    def __init__(self, request):
        self.request = request
        self.token = None
        self.expires_at = 0.0

    def authenticate(self):
        if self.token and time.time() < self.expires_at:
            return
        key, secret = os.getenv("EPO_CONSUMER_KEY"), os.getenv("EPO_CONSUMER_SECRET")
        if not key or not secret:
            raise SourceError("RH_SOURCE_CREDENTIAL", "EPO credentials are missing")
        body = self.request("auth", "POST", BASE + "/3.2/auth/accesstoken",
                            data={"grant_type": "client_credentials"}, auth=(key, secret))
        try:
            result = json.loads(body)
            token, expires = result["access_token"], int(result.get("expires_in", 1199))
            if not isinstance(token, str) or not token:
                raise ValueError("empty token")
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError("RH_SOURCE_INVALID_RESPONSE", "OPS token response is invalid") from exc
        self.token = token
        self.expires_at = time.time() + max(1, expires - 30)

    def get(self, operation, path, *, params=None, range_header=None, accept="application/exchange+xml"):
        self.authenticate()
        headers = {"Accept": accept, "Authorization": "Bearer " + self.token}
        if range_header:
            headers["X-OPS-Range"] = range_header
        return self.request(operation, "GET", BASE + path, headers=headers, params=params)

    def search(self, cql, start, page_size):
        end = start + page_size - 1
        body = self.get("search", "/rest-services/published-data/search/biblio", params={"q": cql},
                        range_header=f"{start}-{end}")
        return parse_search(body, start, page_size), body

    def family(self, publication):
        path = f"/rest-services/family/publication/docdb/{publication['country']}.{publication['publication_number']}.{publication['kind']}"
        body = self.get("family", path, accept="application/ops+xml")
        return parse_family(body), body

    def biblio(self, publication):
        path = f"/rest-services/published-data/publication/docdb/{publication['country']}.{publication['publication_number']}.{publication['kind']}/biblio"
        return self.get("biblio", path)

    def availability(self, publication):
        path=f"/rest-services/published-data/publication/epodoc/{_epodoc(publication)}/fulltext"
        body=self.get("fulltext",path,accept="application/fulltext+xml")
        return parse_availability(body,publication),body

    def section(self, publication, section):
        path = f"/rest-services/published-data/publication/epodoc/{_epodoc(publication)}/{section}"
        body = self.get(section, path, accept="application/fulltext+xml")
        return parse_section(body, section, publication["publication_id"]), body
