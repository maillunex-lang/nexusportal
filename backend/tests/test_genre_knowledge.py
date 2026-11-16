"""Contract tests for the Blueprint -> Game Intelligence research bridge."""
from fastapi import HTTPException
from backend.api.blueprint import genre_knowledge
from tools.game_intelligence import blueprint_context


def test_research_envelope_not_approved():
    data = genre_knowledge("economic_strategy")
    assert data["status"] == "unapproved_knowledge_context"
    assert data["integration_contract"]["approval_granted"] is False
    assert data["research_gaps"]["annual_top100_complete"] is False
    assert data["brief"]["game_dossiers"]
    assert data["sources"]


def test_unknown_genre_is_not_found():
    try:
        genre_knowledge("not-a-genre")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("unknown genre accepted")


def test_research_does_not_create_tasks():
    data = genre_knowledge("mmorpg")
    assert "tasks" not in data
    assert "phases" not in data
    assert data["knowledge_digest"] == blueprint_context("mmorpg")["knowledge_digest"]
