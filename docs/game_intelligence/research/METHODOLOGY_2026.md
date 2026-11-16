# 2026 Top-100 research: methodology and completeness contract

**As of:** 2026-11-16. **Status:** in progress, NOT complete.

## What a "2026 top-100" means
There is no single official Google Play/App Store worldwide annual top-100 for custom subgenres like MMORPG, ARPG, 4X or economic simulation. Store charts are country- and category-specific, and vary by free/paid/grossing. This project must never silently substitute "most famous games" for an observed 2026 ranking.

Use three distinct datasets:
1. **Store chart observations:** date, store, country, store category, free/paid/grossing, observed rank, source URL, app ID, title, developer.
2. **Editorial genre membership:** reviewer-confirmed mechanic-based tags and confidence, possibly multiple genres per game; never infer MMORPG from the store category "Role Playing".
3. **Derived 2026 genre index:** calculated from available 2026 observations with transparent temporal and geographical coverage, not called an official store chart.

## Temporal limitation
AppWinners states its archive began **2026-10-19** and cannot backfill earlier 2026 official charts. Consequently, its daily snapshots alone CANNOT substantiate an annual January–December 2026 top-100. As of 2026-11-16, the year has not finished. Label any present index **2026 year-to-date provisional** and report the covered date interval. Do not fill January–October gaps with guesses. Find separately dated historical sources and state differences in methodology.

Source: https://appwinners.eu/methodology

## Chart-derived ranking algorithm (proposed, not yet computed)
- Deduplicate by stable store app ID + platform, then resolve cross-platform identity manually with confidence.
- For each valid daily chart observation calculate normalized within-chart rank score: `(N+1-rank)/N` where `N` is observed chart depth, not an assumed 100. Keep free/paid/grossing separate.
- For a game and chart dimension, aggregate across observed days with median rank score and days-charted share, **only within actual coverage**. Do not treat unobserved days as zero.
- Report country-specific results by default. Any cross-country index requires explicit published weighting, a minimum coverage threshold and an "estimated" label.
- Classify custom genre memberships with documented evidence, editorial review and confidence. A game in "Strategy" is not automatically 4X.
- For each genre publish a ranked list only when 100 distinct verified eligible games exist and ranking coverage is sufficient. Otherwise publish `observed_count`, `target_count=100`, `coverage_status=incomplete`, `missing_sources`.
- Maintain separate `top_observed` (rank-supported) and `interesting_references` (editorial selection). PC titles like Capitalism Lab belong ONLY in references.

## Legacy partial dataset — verification limitations
`snapshots_2026_11_16.json` retains **143 legacy chart observations**, across six source charts. This is NOT 143 unique games and not 143 eligible custom-genre entries. Android US Strategy has 50 ranks; Android worldwide Simulation has ranks 1–30 and 46–50 with an explicit gap; other snapshots are partial excerpts. Source pages and rank metadata are in `sources.json`.

## Research priorities
- Finish date-scoped chart snapshots for relevant markets and dimensions.
- Resolve stable store IDs and publishers to prevent false cross-platform merges.
- Confirm mechanic-based genres and reject irrelevant store-category matches.
- Gather independently sourced positive AND negative player signals per selected game, including contradictory comments and sampling caveats.
- Publish per-genre coverage manifests and reproducible index calculations.
- Deep-dive Capitalism Lab and other PC references separately.
- Keep individual agent prompts small: fetch only the target genre, its mechanic templates, source IDs and review themes.

## Quality gates
- Every claimed rank has a dated source and matching store/country/chart type.
- Never interpolate ranks across omitted positions.
- Never assert a 2026 full-year ranking before year-end or without historical coverage.
- Never fabricate reviews, player counts, ratings or download/revenue estimates.
- Do not collect personal identifiers or reproduce large copyrighted review texts.
- A green CI validates data integrity, NOT independent truth of each source.


## Batch 2 correction and identity-resolved evidence

A repeat retrieval found chart/date conflicts for three legacy sources; see
`chart_audit.json` and `CHART_EVIDENCE.md`. Historical data is preserved, not silently
rewritten. All legacy rows are excluded from the new resolved reports because they
lack stable app identities; a date-conflicted page also needs archival verification.

`resolved_charts.json` now holds seven sparse source-backed rows with explicit
`chart_date` and `observed_at`, stable app IDs, publishers, identity-source and
genre-source references. The four cohorts must stay separate; the WW Simulation
cohort is a provider estimate. Original store-category ranks are not renumbered
into genre ranks. No annual score is computed from these excerpts and genre
membership remains editorial, so verified genre top-100 counters remain zero.
