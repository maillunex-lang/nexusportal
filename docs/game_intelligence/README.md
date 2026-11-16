# NEXUS Game Intelligence — Knowledge Base v0.1

Status: offline research and deterministic context-export prototype. Not model training and not yet an implemented portal feature.

Current continuation adds 12 primary-source game dossiers spanning all genres, 20 editorial references, 14 player signals and a proposed [Blueprint knowledge envelope](BLUEPRINT_CONTEXT.md). See the [dated checkpoint](research/UPDATE_2026_11_16.md) for limitations. No genre top-100 is complete.

## Goal
Provide Auto Architect with modular, evidence-traceable knowledge about genres, mechanics, technical templates and player sentiment. No paid AI APIs required. Use local search/indexing plus exportable prompts to an external AI assistant.

## Genre curriculum
Priority A: MMORPG, ARPG, 4X/grand strategy, economic strategy, economic simulation.
Priority B: RTS, city builder, survival/crafting, co-op, sandbox, idle RPG, naval strategy, tower defense.
Each genre must cover: core loop, session loop, progression, social play, PvE/PvP, economy, retention, accessibility, monetization pitfalls, backend load, mobile UX, MVP and expansion roadmap, genre-specific anti-patterns.

## Mechanic curriculum
1. Multiplayer: authoritative server, matchmaking, shards, persistent world, reconnect, latency, anti-cheat.
2. Progression: skills, gear, crafting, loot tables, catch-up, endgame.
3. Combat: targeting, hitboxes, cooldowns, balance, PvE/PvP.
4. Social: guilds, clans, alliances, cooperative roles, trading, moderation.
5. Strategy: exploration, expansion, diplomacy, warfare, fog of war, territory, timers.
6. Economy: supply/demand, production chains, logistics, pricing, NPC competition, sinks/sources, inflation, exploits.
7. UX: onboarding, mobile touch, safe areas, clarity, accessibility, session length.
8. Operations: telemetry with privacy, migrations, releases, rollback, live balance.

For each mechanic: purpose, prerequisites, variants, tradeoffs, player frustrations, anti-patterns, data schema, interfaces, simulation/test scenarios, mobile implications, and reference evidence.

## Evidence and reviews
Store feedback as individual source-backed observations with URL, platform, game, genre, publication date, observation date, language, quote <= short excerpt, paraphrase, theme, sentiment, audience segment, sample/bias caveats and confidence.
Never invent player opinions, percentages or ratings. Distinguish developer claims, expert reviews, player comments, and measured outcomes. Group recurring themes but preserve dissenting views. Record both what players enjoy and dislike, and why.
Use legitimate public reviews/discussions and respect site terms, privacy, rate limits and copyright. Do not scrape private accounts or retain user identifiers. For offline curated datasets record provenance and collection date.
Treat review patterns as hypotheses, not universal rules. Use small targeted research batches per genre and update incrementally.

## Recommendation engine
Input: genre mix, platforms, online scale, target audience, session duration, budget, team size, desired complexity.
Output: recommended mechanics and architecture, alternatives, prerequisites, evidence, risks, MVP scope, modular GDD and task DAG.
Separate facts, opinions and recommendations. Give reasons and confidence; expose unknowns.
Do not auto-copy third-party game code, copyrighted assets, names or texts.

## Smart Context integration
Maintain small per-genre and per-mechanic files, machine-readable manifests and explicit dependency edges.
A task retrieves only genre summary, selected mechanics, interfaces and relevant evidence IDs; expandable on demand. Never require reading the entire library.
Preserve isolation between project-specific memory and general knowledge.

## Suggested next implementation stages
GI-01 schemas + validation + source provenance;
GI-02 genre dossiers + mechanic templates;
GI-03 review ingestion with source attribution and deduplication;
GI-04 recommendation rules + conflict detection;
GI-05 Auto Architect wizard integration + contextual prompt export;
GI-06 tests, migration, editorial review workflow.

## Acceptance
No invented sentiment. Each published review insight has traceable evidence. Genre-to-mechanic links validated. No mandatory external AI API. No unrelated VPS changes. Feature should be separately mergeable from portal v1.
