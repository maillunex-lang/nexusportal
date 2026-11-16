# Game Intelligence CLI — first functional vertical slice

Status: **offline prototype**, not yet wired into NEXUS PORTAL UI. No external AI APIs, SSH, secrets, databases or network calls required at runtime.

## Commands
Run from repository root:

```bash
python tools/game_intelligence.py validate
python tools/game_intelligence.py stats
python tools/game_intelligence.py context --genre mmorpg
python tools/game_intelligence.py games --genre economic_strategy
python tools/game_intelligence.py architect --genre economic_strategy
python -m unittest discover -s tests -p "test_game_intelligence.py" -v
```

`validate` checks basic structural integrity, source URLs, genre references, chart rank uniqueness, evidence fields, review source registry and 2026 top-100 coverage tracking.

`context` returns a small, genre-scoped set of blueprint/mechanic/review records. `games` returns an editorial list of candidate reference games with provenance, **not** an annual top-100. `architect` composes a genre-specific design brief, risks, suggested MVP, mechanics, feedback and questions for a later human/AI design workflow.

### Known limitations
- 143 dated chart observations are not 143 unique, app-ID-verified titles and are not a complete top-100 for any of the 12 editorial genres.
- Genre memberships are currently provisional editorial assessments; independent playthrough audits and remaining store identities are pending; the new dossiers include one verified store identity per mobile reference.
- Player signals are a small, self-selected sample; no statistical population claims.
- Market estimates from external analytics companies are not official store financial statements.
- All 12 genres now have first-pass authored MVP/architecture blueprints, but these are design proposals, not independently validated implementation templates.
- Validation proves structural consistency only; it does not prove that a third-party page is historically correct.
- No runtime portal API, UI, scheduler, crawler, historical ranking algorithm or automated source refreshing yet.

## Integration plan
After portal 1.0 lands, expose read-only API endpoints for `genres`, `games`, `context` and `architect` under a feature flag; do not touch the in-progress Claude branch. Require explicit editorial review before an insight can be marked verified. Add a scheduled importer only after licensing, provenance and rate limits are established.

## Primary dossiers and Blueprint preparation

The corpus now includes 12 primary-source game dossiers spanning all 12 genres,
20 editorial reference games and 14 qualitative player signals. New samples retain
publication dates, including older feedback; they are not all 2026 opinions.

```bash
python tools/game_intelligence.py blueprint --genre naval_strategy
```

See [BLUEPRINT_CONTEXT.md](BLUEPRINT_CONTEXT.md) for the versioned envelope,
provenance, corpus digest and approval boundary. See
[the research checkpoint](research/UPDATE_2026_11_16.md) for current gaps.
