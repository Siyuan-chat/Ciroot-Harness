---
title: Crawler and machine-access policy
description: How the CirootHarness documentation site handles search indexing, ChatGPT search eligibility, sitemap discovery, and GitHub Pages crawler constraints.
---

# Crawler and machine-access policy

The CirootHarness documentation site is intended to be publicly discoverable and indexable. Search and generative discovery should point readers back to inspectable public documentation and repository evidence.

## Search indexing

The documentation build provides:

- stable public URLs under `https://siyuan-chat.github.io/Ciroot-Harness/`;
- page-level titles and descriptions;
- canonical URLs generated from the configured `site_url`;
- a generated XML sitemap;
- Open Graph metadata;
- a Schema.org `SoftwareSourceCode` JSON-LD entity;
- an `llms.txt` navigation file.

An XML sitemap helps discovery but does not guarantee indexing or ranking.

## ChatGPT search

OpenAI documents **OAI-SearchBot** as the crawler used to surface public sites in ChatGPT search. **GPTBot** is a separate crawler related to possible model-training use, and the two controls are independent.

CirootHarness's GEO target is that public documentation should remain eligible for search discovery. A separate training-crawler policy should be treated as an independent project policy decision rather than silently inferred from the search goal.

OpenAI crawler reference: <https://developers.openai.com/api/docs/bots>

## Why this project does not ship a subdirectory robots.txt

This documentation site is currently designed as a **GitHub Project Pages** site:

```text
https://siyuan-chat.github.io/Ciroot-Harness/
```

Robots Exclusion Protocol rules are fetched from the **host root**, for example:

```text
https://siyuan-chat.github.io/robots.txt
```

A file at `/Ciroot-Harness/robots.txt` would not control the host-wide crawler policy. For that reason this repository does not publish a misleading project-subdirectory `robots.txt`.

If CirootHarness later moves to a custom domain or a root-level Pages site that it controls, crawler policy should be set at that host's root and verified there.

Google robots reference: <https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec>

## llms.txt status

`llms.txt` is provided as a machine-friendly navigation aid. It is an open community proposal and should not be treated as a guaranteed ranking signal or as a replacement for crawlable HTML, canonical URLs, sitemaps, or high-quality source content.

The file for this project is published at:

```text
https://siyuan-chat.github.io/Ciroot-Harness/llms.txt
```

## Verification

The documentation CI validates that:

- the sitemap exists and contains the canonical CirootHarness URLs;
- the documentation home has the expected canonical URL;
- the structured-data block parses as JSON and identifies the canonical repository;
- `llms.txt` is present and names the canonical entity.

These checks prove build integrity, not search-engine ranking or external crawler behavior.
