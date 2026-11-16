from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.core.db import Database
from backend.core.portal import Portal
from backend.deploy.executor import LocalExecutor
from backend.main import create_app

WEBHOOK_SECRET = "test-webhook-secret-123"
TOKEN = "ghp_" + "A" * 36


class FakeGitHub:
    """Минимальная in-memory модель GitHub REST API для тестов."""

    def __init__(self):
        self.repos: dict[str, dict] = {}
        self.files: dict[tuple[str, str, str], str] = {}  # (repo, branch, path) -> content
        self.branches: dict[tuple[str, str], str] = {}
        self.prs: dict[tuple[str, int], dict] = {}
        self.check_runs: dict[tuple[str, str], list[dict]] = {}
        self.protection: dict[tuple[str, str], list[str]] = {}
        self.runs: dict[int, dict] = {}
        self.artifacts: dict[int, list[dict]] = {}
        self.artifact_blobs: dict[int, bytes] = {}
        self.merges: list[dict] = []
        self.created_files: list[str] = []
        self.auth_seen: set[str] = set()
        self.telegram: list[dict] = []
        self.max: list[dict] = []

    def add_repo(self, name: str, files: dict[str, str] | None = None, branch: str = "main"):
        self.repos[name] = {"full_name": name, "default_branch": branch, "private": True, "description": ""}
        self.branches[(name, branch)] = "base" + "0" * 36
        for p, c in (files or {}).items():
            self.files[(name, branch, p)] = c

    def add_pr(self, repo, number, branch, sha, title="PR", fork=False, mergeable=True):
        self.branches[(repo, branch)] = sha
        self.prs[(repo, number)] = {
            "number": number, "title": title, "state": "open", "merged": False, "draft": False,
            "mergeable": mergeable, "html_url": f"https://github.com/{repo}/pull/{number}",
            "head": {"ref": branch, "sha": sha, "repo": {"full_name": "evil/fork" if fork else repo}},
            "base": {"ref": "main"}, "merge_commit_sha": None,
        }
        return self.prs[(repo, number)]

    def set_check(self, repo, sha, name, conclusion, status="completed", run_id=None):
        runs = self.check_runs.setdefault((repo, sha), [])
        runs.append({"id": len(runs) + 1, "name": name, "head_sha": sha, "status": status,
                     "conclusion": conclusion, "html_url": f"https://ci/{name}",
                     "details_url": f"https://github.com/{repo}/actions/runs/{run_id or 77}/job/1",
                     "output": {"summary": f"{name}: {conclusion}"}})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        host = url.host
        if host == "api.telegram.org":
            self.telegram.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True})
        if host == "platform-api.max.ru":
            self.max.append({"params": dict(url.params), "auth": request.headers.get("authorization"),
                             **json.loads(request.content)})
            return httpx.Response(200, json={"message": {}})
        self.auth_seen.add(request.headers.get("authorization", ""))
        path = url.path
        m = request.method
        if path == "/user":
            return httpx.Response(200, json={"login": "owner"})
        if m == "POST" and path == "/user/repos":
            body = json.loads(request.content)
            name = "owner/" + body["name"]
            self.add_repo(name)
            self.files[(name, "main", "README.md")] = "# init"
            return httpx.Response(201, json=self.repos[name])
        mm = re.match(r"^/repos/([^/]+/[^/]+)(/.*)?$", path)
        if not mm:
            return httpx.Response(404, json={"message": "Not Found"})
        repo, rest = mm.group(1), mm.group(2) or ""
        if repo not in self.repos:
            return httpx.Response(404, json={"message": "Not Found"})
        if rest == "":
            return httpx.Response(200, json=self.repos[repo])
        if r := re.match(r"^/git/trees/(.+)$", rest):
            br = r.group(1)
            tree = [{"path": p, "type": "blob"} for (rp, b, p) in self.files if rp == repo and b == br]
            return httpx.Response(200, json={"tree": tree})
        if r := re.match(r"^/contents/(.+)$", rest):
            fpath = r.group(1)
            if m == "GET":
                ref = url.params.get("ref", "main")
                c = self.files.get((repo, ref, fpath))
                if c is None:
                    return httpx.Response(404, json={"message": "Not Found"})
                return httpx.Response(200, json={"content": base64.b64encode(c.encode()).decode(),
                                                 "sha": hashlib.sha1(c.encode()).hexdigest()})
            if m == "PUT":
                body = json.loads(request.content)
                key = (repo, body["branch"], fpath)
                if key in self.files and "sha" not in body:
                    return httpx.Response(422, json={"message": "sha wasn't supplied"})
                self.files[key] = base64.b64decode(body["content"]).decode()
                self.created_files.append(fpath)
                return httpx.Response(201, json={"content": {"path": fpath}})
        if r := re.match(r"^/git/ref/heads/(.+)$", rest):
            sha = self.branches.get((repo, r.group(1)))
            if not sha:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"object": {"sha": sha}})
        if rest == "/git/refs" and m == "POST":
            body = json.loads(request.content)
            br = body["ref"].removeprefix("refs/heads/")
            self.branches[(repo, br)] = body["sha"]
            base = next(b for (rp, b), s in self.branches.items() if rp == repo and s == body["sha"])
            for (rp, b, p), c in list(self.files.items()):
                if rp == repo and b == base:
                    self.files[(repo, br, p)] = c
            return httpx.Response(201, json={})
        if rest == "/pulls" and m == "POST":
            body = json.loads(request.content)
            n = max([k[1] for k in self.prs if k[0] == repo] + [0]) + 1
            pr = self.add_pr(repo, n, body["head"], self.branches[(repo, body["head"])], body["title"])
            return httpx.Response(201, json=pr)
        if rest == "/pulls":
            st = url.params.get("state", "open")
            return httpx.Response(200, json=[p for (rp, _), p in self.prs.items() if rp == repo and p["state"] == st])
        if r := re.match(r"^/pulls/(\d+)$", rest):
            pr = self.prs.get((repo, int(r.group(1))))
            return httpx.Response(200, json=pr) if pr else httpx.Response(404, json={"message": "Not Found"})
        if r := re.match(r"^/pulls/(\d+)/merge$", rest):
            pr = self.prs[(repo, int(r.group(1)))]
            body = json.loads(request.content)
            if body.get("sha") != pr["head"]["sha"]:
                return httpx.Response(409, json={"message": "Head branch was modified"})
            pr.update(state="closed", merged=True, merge_commit_sha="m" * 40)
            self.merges.append({"repo": repo, "number": pr["number"], "sha": body["sha"]})
            return httpx.Response(200, json={"merged": True, "sha": "m" * 40})
        if r := re.match(r"^/commits/([^/]+)/check-runs$", rest):
            return httpx.Response(200, json={"check_runs": self.check_runs.get((repo, r.group(1)), [])})
        if r := re.match(r"^/commits/([^/]+)/status$", rest):
            return httpx.Response(200, json={"statuses": []})
        if r := re.match(r"^/branches/(.+)/protection/required_status_checks$", rest):
            names = self.protection.get((repo, r.group(1)))
            if names is None:
                return httpx.Response(404, json={"message": "Branch not protected"})
            return httpx.Response(200, json={"contexts": names, "checks": []})
        if rest == "/commits":
            return httpx.Response(200, json=[{"sha": "c1", "commit": {"message": "init", "author": {"name": "a"}}}])
        if r := re.match(r"^/actions/runs/(\d+)$", rest):
            return httpx.Response(200, json=self.runs[int(r.group(1))])
        if r := re.match(r"^/actions/runs/(\d+)/artifacts$", rest):
            return httpx.Response(200, json={"artifacts": self.artifacts.get(int(r.group(1)), [])})
        if r := re.match(r"^/actions/runs/(\d+)/jobs$", rest):
            return httpx.Response(200, json={"jobs": [{"name": "tests", "conclusion": "failure",
                                                       "steps": [{"name": "pytest", "conclusion": "failure"}]}]})
        if r := re.match(r"^/actions/artifacts/(\d+)/zip$", rest):
            return httpx.Response(200, content=self.artifact_blobs[int(r.group(1))],
                                  headers={"content-type": "application/zip"})
        return httpx.Response(404, json={"message": f"Not mocked: {m} {path}"})


@pytest.fixture
def fake_gh():
    return FakeGitHub()


@pytest.fixture
def portal(tmp_path, fake_gh):
    secrets = tmp_path / "secrets"
    st = Settings(data_dir=tmp_path, secrets_dir=secrets, db_path=tmp_path / "db.sqlite3",
                  cookie_secure=False, frontend_dist=None, deploy_root=str(tmp_path / "srv"),
                  public_download_base="https://dl.example.org", sync_interval_minutes=0)
    st.write_secret("github_token", TOKEN)
    st.write_secret("github_webhook_secret", WEBHOOK_SECRET)
    db = Database(st.db_path)
    db.migrate()
    p = Portal(st, db, http_transport=httpx.MockTransport(fake_gh),
               executor_factory=lambda portal, project, env: LocalExecutor())
    return p


@pytest.fixture
def client(portal):
    from backend.api.auth import login_limiter
    login_limiter.hits.clear()
    app = create_app(portal=portal, background_sync=False)
    portal.auth.set_owner("owner", "correct horse battery")
    return TestClient(app)


@pytest.fixture
def authed(client):
    r = client.post("/api/auth/login", json={"username": "owner", "password": "correct horse battery"})
    assert r.status_code == 200
    client.headers["x-csrf-token"] = r.json()["csrf_token"]
    return client


def sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def make_project(portal, repo="owner/game", **kw) -> dict:
    vals = {"slug": kw.pop("slug", "game"), "name": "Игра", "kind": "game", "template": "godot",
            "repo_full_name": repo, "default_branch": "main", "auto_merge_enabled": 1,
            "required_checks": '["tests"]'}
    vals.update(kw)
    pid = portal.db.insert("projects", vals)
    return portal.project(pid)
