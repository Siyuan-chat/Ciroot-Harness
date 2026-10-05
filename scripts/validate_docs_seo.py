from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SITE_URL = "https://siyuan-chat.github.io/Ciroot-Harness/"
REPO_URL = "https://github.com/Siyuan-chat/Ciroot-Harness"
EXPECTED_URLS = {
    SITE_URL,
    SITE_URL + "getting-started/",
    SITE_URL + "current-status/",
    SITE_URL + "concepts/auditable-ai-research/",
    SITE_URL + "concepts/evidence-traceability/",
    SITE_URL + "concepts/local-rag-scientific-literature/",
    SITE_URL + "concepts/ai-patent-research/",
    SITE_URL + "concepts/research-agent-vs-research-harness/",
    SITE_URL + "concepts/reproducible-ai-research-workflows/",
    SITE_URL + "glossary/",
    SITE_URL + "crawler-policy/",
}


def fail(message: str) -> None:
    raise SystemExit(f"SEO validation failed: {message}")


def require(path: Path) -> str:
    if not path.is_file():
        fail(f"missing {path}")
    return path.read_text(encoding="utf-8")


def main() -> None:
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "site")

    index_html = require(site / "index.html")
    sitemap_xml = require(site / "sitemap.xml")
    llms_txt = require(site / "llms.txt")

    canonical = re.search(
        r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']',
        index_html,
        flags=re.IGNORECASE,
    )
    if not canonical:
        fail("home page has no canonical link")
    if canonical.group(1) != SITE_URL:
        fail(f"unexpected home canonical: {canonical.group(1)!r}")

    json_ld_blocks = re.findall(
        r'<script\s+type=["\']application/ld\+json["\']\s*>(.*?)</script>',
        index_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not json_ld_blocks:
        fail("home page has no JSON-LD block")

    entities = []
    for block in json_ld_blocks:
        try:
            entities.append(json.loads(block))
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON-LD: {exc}")

    source_entities = [
        entity for entity in entities if entity.get("@type") == "SoftwareSourceCode"
    ]
    if not source_entities:
        fail("no SoftwareSourceCode JSON-LD entity found")

    source = source_entities[0]
    if source.get("name") != "CirootHarness":
        fail("structured entity name is not CirootHarness")
    if source.get("codeRepository") != REPO_URL:
        fail("structured entity points to the wrong repository")

    try:
        root = ET.fromstring(sitemap_xml)
    except ET.ParseError as exc:
        fail(f"invalid sitemap XML: {exc}")

    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = {
        element.text.strip()
        for element in root.findall(".//sm:loc", namespace)
        if element.text
    }
    missing = sorted(EXPECTED_URLS - urls)
    if missing:
        fail("sitemap is missing canonical URLs: " + ", ".join(missing))

    if not llms_txt.startswith("# CirootHarness\n"):
        fail("llms.txt does not start with the canonical entity name")
    if REPO_URL not in llms_txt:
        fail("llms.txt does not reference the canonical repository")
    if "production-ready end-to-end patent research" not in llms_txt:
        fail("llms.txt is missing the patent capability boundary")

    print(
        f"SEO validation passed: {len(urls)} sitemap URLs, "
        f"{len(json_ld_blocks)} JSON-LD block(s), canonical={SITE_URL}"
    )


if __name__ == "__main__":
    main()
