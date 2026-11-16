# Continuation batch 2 — dated charts, reviews and genre mechanics

Baseline: `a52bf72998a2229e1a24a81bc46482650cd96ba6`, same branch and PR #2. No main merge, other branch mutation, VPS changes, external AI API or background automation.

## Added research

- Four primary-source dossiers: Whiteout Survival, Kingshot, Township and The Tower. Corpus now contains 16 dossiers and 21 editorial reference games.
- Twelve individually sourced player signals, bringing the corpus to 26. Includes three Sim Companies reviews about strategy/fairness, deposit rerolls and assistant delegation; mixed Minecraft touch feedback; Bloons strategy/account/performance feedback; a Titan Quest quest-save report; opposing SimCity update/purchase opinions and an editing request; Township social discovery, Kingshot advertised-loop and Whiteout merger concerns.
- Dates remain explicit: six of the new observations were published in 2026 and six in 2025. No current-version defect, actual odds, representative sentiment or retention improvement is claimed from these anecdotes. No user identifiers or full review text stored.
- Source registry: 44 entries, including primary listings/reviews, chart excerpts and app identity pages.

## Corrected evidence handling

Repeated source retrieval exposed displayed-date and rank conflicts in three legacy charts. Added `chart_audit.json` to retain the historical rows and their uncertainty rather than silently rewriting them. All 143 legacy rows are excluded from new resolved reports pending stable IDs and archive checks. The iOS US excerpt matches its date/first 14 positions; two sources were not rechecked in this batch.

Added seven sparse identity-resolved rows for six games across four cohorts. Each records the displayed chart date, retrieval date, original category rank, publisher, app ID, identity source and genre source. WW Simulation is a provider estimate. Country and worldwide evidence are never pooled. These observations do not complete a genre top-100 or prove independent genre eligibility; coverage counters remain zero.

## Code and design templates

- New `charts --genre <id>` command returns separate evidence cohorts and explicit empty results.
- Blueprint envelope includes chart evidence, related provenance and updated corpus digest covering eleven inputs.
- Validation checks cohort/source dimensions, estimate labels, date intervals, duplicate ranks/identities/cohorts, mobile identity, publisher/genre provenance, legacy audits and store-review dates/locators.
- Eight authored mechanic templates added: RTS commands, survival crafting, sandbox editing, idle rewards, naval navigation, wave defense, cooperative sessions and city services. All 12 genres now have at least one applicable mechanic contract/test set; total 20 templates. These are engineering proposals, not copied game implementations or validated reusable code.
- Docs: `CHART_EVIDENCE.md`, updated usage, methodology and envelope contract.

## Validation

`python tools/game_intelligence.py validate`: passes.

`python -m unittest discover -s tests`: **80 tests pass** (61 Game Intelligence, 19 adaptive project), including 24 tests added in this batch.

`git diff --check`: passes.

GitHub CI must be checked on the newly published commit; local results do not stand in for Actions results.

## Next bounded research block

Resolve additional chart rows with stable IDs and dated archives; audit full genre pillars; gather opposing opinions for games with empty review samples (notably Rise of Kingdoms); extend sources across countries and paid/free/grossing dimensions. Do not create an annual score from seven selected observations or pad sparse genres to 100.
