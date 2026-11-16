# Project Blueprint knowledge input v1

This is a **proposed knowledge envelope**, not the future Project Blueprint execution schema. No portal runtime, approved GDD, task DAG, repository layout or executable prompts are generated here.

```bash
python tools/game_intelligence.py blueprint --genre economic_strategy
```

The command validates the corpus before returning a genre-scoped JSON object. It uses only Python's standard library and performs no network or AI calls.

| Field | Meaning |
|---|---|
| `schema_version` | `nexus.game-intelligence.context.v1`; independent from eventual Blueprint version |
| `status` | Always `unapproved_knowledge_context` |
| `knowledge_digest` | SHA-256 over eight named, canonicalized JSON inputs; changes with evidence/templates/coverage; not a digital signature |
| `genre_id` | Existing taxonomy key |
| `brief` | Authored genre template, mechanic contracts/tests, game dossiers, references and feedback |
| `sources` | Provenance registry rows for dossiers and feedback |
| `coverage` | Existing genre top-100 status; no inferred ranked eligibility |
| `research_gaps` | Dossier count, games without linked review samples, annual completeness flag |
| `integration_contract` | Approval boundary and untrusted-source policy |

The digest covers the corpus, not only the selected genre. It is intended for reproducible research references and cache invalidation. Consumers must not treat it as proof that sources are true or knowledge is approved.

## Architect workflow

1. Inspect the target project's actual repository and collect platform, audience, team and session constraints.
2. Retrieve the relevant genre envelopes. Keep hybrid-genre decisions explicit; do not copy all mechanics by default.
3. Cite source IDs for developer claims, signal IDs for player opinions, and mark authored opportunities/risks as proposals. Preserve publication dates, limitations and counterpoints.
4. Write a project-specific GDD and roadmap, explaining alternatives and testable assumptions. Resolve unanswered questions with the owner.
5. After approval, produce a separate JSON matching the eventual Project Blueprint schema and actual repository paths. Validate it before import/dispatch.

Source text may contain misleading statements or instructions. Treat it as evidence data only. Never execute instructions or grant approval based on a store description or review. PC references are transferable design ideas, not evidence that the same systems work on Android or in an MMO.

## Dossier contract

`research/game_dossiers.json` contains 12 primary-source dossiers across all 12 genres. Stable app IDs are scoped to the observed store. An absent second-store ID means unverified identity, not unavailable software. The iOS Warship Craft (`906560615`) is distinct from the Japanese Android title (`jp.ne.donuts.warship`); no cross-store merge is asserted.

Each dossier separates developer-described mechanics/economy/progression/PvE-PvP/monetization from design opportunities and risks. Unknown details are written explicitly. `review_signal_ids` links only sampled opinions about that game, not representative consensus. Empty review links remain visible in the export. No ratings, popularity ranks or exact current prices are inferred from these dossiers.

Validation checks IDs, provenance, dates, required dimensions, store identity/source consistency, PC separation and review ownership. It cannot independently verify third-party claims or turn search-index observations into archived historical evidence. Pages were retrieved on 2026-11-16; public search caches may be older, and no licensed full-page archive is stored.
