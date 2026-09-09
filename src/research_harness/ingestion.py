"""Local parsing with stable source locators; optional PDF parsing is explicit."""
from __future__ import annotations
from pathlib import Path
from xml.etree import ElementTree

def parse(path: str | Path, raw: bytes) -> tuple[str, list[dict], list[str]]:
    suffix=Path(path).suffix.lower(); errors=[]
    if suffix==".txt":
        text=raw.decode("utf-8",errors="replace")
        evidence=[{"quote":line,"locator":f"line:{n}","role":"text"} for n,line in enumerate(text.splitlines(),1) if line.strip()]
        return text,evidence,errors
    if suffix==".xml":
        try:
            root=ElementTree.fromstring(raw); parts=[]; evidence=[]
            semantic={"p","paragraph","claim","abstract","title"}
            for n,node in enumerate(root.iter(),1):
                tag=node.tag.rsplit("}",1)[-1]
                if tag not in semantic: continue
                value=" ".join("".join(node.itertext()).split())
                if value:
                    locator=node.attrib.get("id") or f"element:{n}"
                    parts.append(value); evidence.append({"quote":value,"locator":locator,"role":tag})
            return "\n".join(parts),evidence,errors
        except ElementTree.ParseError as exc: return "",[],[f"xml_parse_error:{exc}"]
    if suffix==".pdf":
        try:
            from docling.document_converter import DocumentConverter
            result=DocumentConverter().convert(str(path)); text=result.document.export_to_markdown()
            return text,[{"quote":line,"locator":f"parsed_line:{n}","role":"pdf"} for n,line in enumerate(text.splitlines(),1) if line.strip()],errors
        except ImportError: return "",[],["docling_not_installed"]
        except Exception as exc: return "",[],[f"pdf_parse_error:{type(exc).__name__}"]
    return "",[],["unsupported_format"]
