# Chart dates, identity resolution and uncertainty

Retrieved 2026-11-16. This is a small, manually checked research batch using public pages, not a crawler or an official store data feed. Search/open retrieval may return cached content. The date printed on a chart is recorded separately from retrieval date; no historical date is inferred from a URL containing `today`.

## Repeated retrieval changed the evidence status

| Legacy source | Previously recorded date | Displayed on repeat retrieval | Result |
|---|---|---|---|
| Android US Strategy grossing | 2026-11-16 | 2026-11-15 | Date and position conflict |
| Android WW Simulation grossing | 2026-11-16 | 2026-11-13 | Date and position conflict; provider estimate |
| iOS US Games grossing | 2026-11-16 | 2026-11-16 | First 14 positions match; IDs still unresolved in legacy data |
| iOS DE Games grossing | 2026-11-16 | 2026-11-15 | Date and position conflict |
| Android WW RPG grossing | 2026-11-16 | Not rechecked | Needs archival/date verification |
| Android DE Simulation free | 2026-11-16 | Not rechecked | Needs archival/date verification |

The original 143 rows remain available for audit, but none enters the new identity-resolved report. A discrepancy is not proof the old page never displayed that data; live URLs and cached variants are insufficient to establish its original historical state. Do not patch legacy dates by guessing that old ranks belonged to the newly displayed day.

## New sparse observations

| Store / country / category / metric | Chart date | Original category positions captured |
|---|---|---|
| Google Play / US / Strategy / grossing | 2026-11-15 | Kingshot 1; Whiteout Survival 3; Rise of Kingdoms 17 |
| Google Play / WW / Simulation / grossing | 2026-11-13 | The Tower 16; SimCity BuildIt 24; **provider estimate** |
| App Store / US / Games / grossing | 2026-11-16 | Township 12 |
| App Store / DE / Games / grossing | 2026-11-15 | Township 11 |

Sources:
- https://appwinners.eu/charts/android/us/grossing/game-strategy
- https://appwinners.eu/charts/android/ww/grossing/game-simulation
- https://appwinners.eu/charts/ios/us/grossing/games
- https://appwinners.eu/charts/ios/de/grossing/games

These seven rows represent six distinct editorial reference games. They are not a top-seven, a genre rank, seven independent samples, or evidence of yearly popularity. Township appearing in two countries is one game and two observations. Publisher/app-page links were followed to establish the store IDs recorded in `resolved_charts.json`; source IDs are registered in `sources.json`. Identity pages may display a different day and support only identity here, not the captured cohort rank.

The `charts` CLI preserves store/country/category/metric/date boundaries and reports no combined score. A worldwide estimate is never promoted to an official country chart. PC references cannot enter because they have no matching mobile store identity. Genre memberships remain explicit editorial assessments requiring independent mechanics audits. Full 4X eligibility is not guaranteed by a store tag; a package called `tower.defense` does not prove Tower Defense gameplay.

## Next research checks

Obtain stable dated archive URLs or permitted licensed exports, broaden countries and chart dimensions, disambiguate more titles with publisher/store IDs, independently audit genre pillars, and sample player views on both sides of design tradeoffs. Only then consider a published year-to-date index with explicit coverage/weighting. Do not normalize sparse rank gaps into a fictitious full chart.
