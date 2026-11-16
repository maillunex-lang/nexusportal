# Research continuation: 2026 live-ops and design hypotheses

**Scope:** six selected dated case studies, not a representative sample, annual top-100, proof of causal uplift or verified player sentiment.

The dataset `research/live_ops_cases_2026.json` separates reported observations from proposed game design hypotheses. Each case has a date, original industry source, genre mapping, mechanics, testable questions and limitations. Adjacent genre examples are explicitly labeled rather than inserted into the target genre ranking.

## Research patterns

- **4X / alliances:** Whiteout Survival's June and August event reporting suggests studying both cooperative goals and leaderboard competition. The proposed accessibility of small groups is an experiment, not an observed user preference.
- **MMORPG:** SOL: enchant's described player economy, rule creation and offline play are interesting design references, but developer claims should be tested for exploit resistance and fairness before reuse.
- **ARPG adjacent:** Honor of Kings is a MOBA, so its temporary combat modes can inspire event design but must not be classified as an ARPG chart entry.
- **Sandbox:** Roblox is a multi-genre creator platform. Its broad catalog suggests investigating discovery and safety, not inferring a standalone sandbox ranking.
- **Economic simulation / city builder adjacent:** Gossip Harbor is a merge game. Its narrative live-ops is a cross-genre inspiration, not evidence that city-builder users want mandatory timed collections.

## Reproduction

```bash
python tools/game_intelligence_liveops.py validate
python tools/game_intelligence_liveops.py cases --genre mmorpg
python -m unittest discover -s tests -p 'test_game_intelligence_liveops.py' -v
```

This is a **separate research dataset**. It does not change the existing annual coverage counters, genre dossiers, or the v1 Blueprint context digest. The next integration step should add a clearly labeled optional `live_ops_cases` field to the knowledge envelope and update the digest and tests together, without treating these cases as ranked evidence.

No VPS, paid AI APIs or main-branch changes.
