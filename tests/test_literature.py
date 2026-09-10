import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_harness import literature


class Response:
    def __init__(self, status_code=200, payload=None, data=b"", headers=None):
        self.status_code = status_code
        self._payload = payload
        self._data = data
        self.headers = headers or {}

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=65536):
        yield self._data

    def close(self):
        pass


class Session:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses[url]
        return response() if callable(response) else response


def record(title="Verified AEM paper", doi="10.1/example", url="https://files.example/paper.pdf"):
    return {"title": title, "doi": doi, "year": 2024, "authors": ["A. Author"], "type": "article", "locations": [{"is_oa": True, "pdf_url": url, "landing_page_url": None, "license": "CC-BY", "version": "publishedVersion"}]}


class LiteratureTests(unittest.TestCase):
    def test_anonymous_search_deduplicates_and_records_partial_cursor(self):
        payload = {"results": [{"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/example", "title": "AEM review", "publication_year": 2024, "type": "review", "authorships": [{"author": {"display_name": "Author"}}], "locations": [], "abstract_inverted_index": {"review": [1], "AEM": [0]}}], "meta": {"next_cursor": "next"}}
        session = Session({literature.OPENALEX_URL: Response(payload=payload)})
        result = literature.search({"queries": ["AEM"], "year_min": 2020, "title_search": "anion exchange membrane", "review_only": False, "max_candidates": 150, "max_pages_per_query": 1, "anonymous": True}, session=session)
        self.assertEqual("partial", result["search_status"]["status"])
        self.assertEqual("AEM review", result["records"][0]["title"])
        self.assertEqual("AEM review", result["records"][0]["abstract"])
        self.assertNotIn("Authorization", session.calls[0][1]["headers"])
        self.assertEqual(100, session.calls[0][1]["params"]["per-page"])
        self.assertIn("title.search:anion exchange membrane", session.calls[0][1]["params"]["filter"])

    def test_search_requires_key_or_explicit_anonymous_mode(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(literature.LiteratureError, "OPENALEX_API_KEY"):
                literature.search({"queries": ["AEM"], "year_min": 2020, "review_only": False, "max_candidates": 10, "max_pages_per_query": 1})

    def test_download_preserves_partial_work_and_reuses_verified_pdf(self):
        good = "https://files.example/good.pdf"
        html = "https://files.example/html.pdf"
        session = Session({good: Response(data=b"%PDF-good"), html: Response(data=b"<html>not a PDF</html>")})
        with tempfile.TemporaryDirectory() as directory, patch("research_harness.literature._safe_url", side_effect=lambda url: url), patch("research_harness.literature._pdf_check", side_effect=lambda data, _: (1, data == b"%PDF-good", False)):
            first_record = record(url=good)
            first_record["locations"][0]["landing_page_url"] = "https://files.example/unused-landing"
            manifest = {"records": [first_record, record(title="Duplicate bytes", doi="10.1/other", url=good), record(title="HTML", doi="10.1/html", url=html)]}
            first = literature.download(manifest, directory, limit=2, session=session)
            second = literature.download(manifest, directory, limit=2, session=session)
            self.assertTrue((Path(directory) / "catalog.csv").exists())
            self.assertTrue((Path(directory) / "references.bib").exists())
        self.assertEqual("partial", first["outcome"])
        self.assertEqual(1, first["valid_pdf_count"])
        self.assertEqual("duplicate", first["records"][1]["download"]["status"])
        self.assertTrue(any(item["download"]["status"] == "success" for item in second["records"]))
        self.assertNotIn("https://files.example/unused-landing", [url for url, _ in session.calls])

    def test_byte_budget_stops_following_records(self):
        first = "https://files.example/first.pdf"
        second = "https://files.example/second.pdf"
        session = Session({first: Response(data=b"%PDF-first"), second: Response(data=b"%PDF-second")})
        with tempfile.TemporaryDirectory() as directory, patch("research_harness.literature._safe_url", side_effect=lambda value: value), patch("research_harness.literature.MAX_TOTAL_BYTES", 1):
            result = literature.download({"records": [record(doi="10.1/first", url=first), record(doi="10.1/second", url=second)]}, directory, limit=2, session=session)
        self.assertEqual("partial", result["outcome"])
        self.assertEqual([first], [url for url, _ in session.calls])

    def test_private_url_and_identity_mismatch_do_not_become_success(self):
        with self.assertRaisesRegex(literature.LiteratureError, "non-public"):
            literature._safe_url("http://127.0.0.1/paper.pdf")
        url = "https://files.example/wrong.pdf"
        session = Session({url: Response(data=b"%PDF-wrong")})
        with tempfile.TemporaryDirectory() as directory, patch("research_harness.literature._safe_url", side_effect=lambda value: value), patch("research_harness.literature._pdf_check", return_value=(2, False, False)):
            result = literature.download({"records": [record(doi="10.1/wrong", url=url)]}, directory, limit=1, session=session)
        self.assertEqual("partial", result["outcome"])
        self.assertEqual("review", result["records"][0]["download"]["status"])
