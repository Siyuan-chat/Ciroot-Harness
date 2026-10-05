# Frontend Productization — Local Implementation Acceptance (2026-09-28)

## Scope and result

The accepted Research Workspace design was implemented locally by Luna in the staged PR 2–5 scope. Sol independently accepted each fixed candidate. This record is a local implementation acceptance, not Product Launch Acceptance or evidence of published GitHub pull requests.

The resulting UI has Overview, Library, Investigations, Reports & Review, and Settings as its primary destinations. Overview plans a question through the existing assistant draft without sending or executing it. Its Offline Demo action uses the canonical GUI adapter and opens the returned run. The Investigation workspace shows source coverage, evidence, progress, structured claims, and read-only run issues. Reports bind `section.claim_ids` to claims and their explicit `evidence_refs`; evidence chips open a contextual Inspector with the exact excerpt, source/version/locator, and an explicit unavailable-original state. Reports & Review includes a scoped read-only run issue inbox. Monitor reviews remain on the existing `monitor_id` route because the service does not provide safe global monitor enumeration.

## Independent checks

- `frontend`: `npm run check`, `npm test` (74 passed), and `npm run build` passed on the final candidate.
- Python: all `tests/test_gui_*.py` plus `tests/test_golden_demo.py` passed (48 passed; one Starlette/AnyIO deprecation warning).
- `git diff --check` passed.
- The actual local browser opened the canonical Offline Demo and observed a persisted synthetic run with `outcome=partial`, two verified claims, and one open normalization issue. The browser followed Overview → Investigation → Report → evidence chip → Evidence Inspector, then used Escape to close the Inspector and return focus to its chip. The read-only review inbox showed `RH_NORMALIZE_XML` and opened the corresponding Investigation without a decision control.
- Rendered browser checks covered 1440×900, 1280×800, 1024×768, and 390×844. English, Chinese, and Japanese were checked at desktop and narrow widths. The 390px content and assistant states each used the full main width. The Evidence Inspector was visible as a full-screen sheet at 390px. Browser viewport overrides were reset after QA.

## Preserved semantics

`partial` remained distinct from completed and failed. Golden Demo remained synthetic and offline. Unknown counts and unavailable sources were represented explicitly. Patent Compare appeared only for explicit patent metadata; the Golden Demo bibliography is typed `misc`, so it did not appear. Run issues were read-only and were not wired to monitor decision writes. Report citations were built from structured references, without inferred inline positions.

## Publication and remaining release boundary

GitHub CLI authentication was restored. The five requested pull requests were created as a stacked review chain without staging unrelated files from the shared checkout:

| Stage | PR | Head | Base |
| --- | --- | --- | --- |
| PR1 design | [#5](https://github.com/Siyuan-chat/autoSearch-Harness/pull/5) | `daa39fc` | `master` |
| PR2 Overview and Demo | [#6](https://github.com/Siyuan-chat/autoSearch-Harness/pull/6) | `1527c9b` | PR #4 Golden Demo |
| PR3 Investigation | [#7](https://github.com/Siyuan-chat/autoSearch-Harness/pull/7) | `f3bfc72` | PR #6 |
| PR4 Report and Evidence | [#8](https://github.com/Siyuan-chat/autoSearch-Harness/pull/8) | `4f1d645` | PR #7 |
| PR5 visual system | [#9](https://github.com/Siyuan-chat/autoSearch-Harness/pull/9) | `4462aaa` | PR #8 |

At these heads, GitHub Frontend and Python 3.11/3.12 checks passed for all five PRs. PR2 had actual browser checks at 1440×900, 1280×800, 1024×768, and 390×844 and desktop/narrow EN/ZH/JA, including a repaired 390px assistant layout. The user then requested faster publication without repeating Demo and extensive checks; PR3–5 used targeted local checks plus full remote CI, and their browser visual QA was not repeated. PR2–5 depend on upstream PR branches and have not been merged. Packaged desktop acceptance and independent Product Launch Acceptance remain pending; these PRs do not assert an open-source release.
