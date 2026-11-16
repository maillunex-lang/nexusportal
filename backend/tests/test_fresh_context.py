from unittest.mock import Mock, patch
import pytest
from backend.github.client import GitHubError
from backend.github.fresh_context import snapshot, appendix


def setup_portal(shas):
    p = Mock()
    gh = Mock()
    gh.branch_sha.side_effect = shas
    p.github.return_value = gh
    p.db.all.side_effect = [[{"task_key": "T1", "status": "done", "pr_number": 4}], [{"number": 5, "title": "Next", "ci_state": "pending", "head_sha": "abc"}]]
    return p


def test_fresh_snapshot():
    p = setup_portal(["abc", "abc"])
    with patch("backend.github.fresh_context.sync_project", return_value={"open_prs": 1}):
        data = snapshot(p, {"id": 2, "repo_full_name": "owner/repo", "default_branch": "main"})
    assert data["main_sha"] == "abc"
    assert data["tasks"][0]["status"] == "done"
    assert "T1: done" in appendix(data)
    assert "CI=pending" in appendix(data)


def test_sha_race_rejected():
    p = setup_portal(["abc", "def"])
    with patch("backend.github.fresh_context.sync_project", return_value={}):
        with pytest.raises(GitHubError) as err:
            snapshot(p, {"id": 2, "repo_full_name": "owner/repo"})
    assert err.value.status == 409


def test_api_failure_not_replaced_with_cache():
    p = setup_portal(["abc"])
    with patch("backend.github.fresh_context.sync_project", side_effect=GitHubError(502, "unavailable")):
        with pytest.raises(GitHubError):
            snapshot(p, {"id": 2, "repo_full_name": "owner/repo"})
    p.db.all.assert_not_called()


def test_missing_repo_rejected():
    with pytest.raises(GitHubError):
        snapshot(Mock(), {"id": 2})
