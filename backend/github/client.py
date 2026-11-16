"""Клиент GitHub REST API. Токен читается на сервере и никогда не отдаётся наружу."""
from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx

from ..core.redact import redact


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub {status}: {message}")
        self.status = status


class GitHubClient:
    def __init__(self, token: str | None, api: str = "https://api.github.com",
                 transport: httpx.BaseTransport | None = None, allowed_repos: list[str] | None = None):
        self._token = token
        self.allowed_repos = [r.lower() for r in (allowed_repos or [])]
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "nexus-portal"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.http = httpx.Client(base_url=api, headers=headers, timeout=30, transport=transport,
                                 follow_redirects=True)

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def check_repo(self, repo: str) -> None:
        if "/" not in repo or repo.count("/") != 1:
            raise GitHubError(400, "Некорректное имя репозитория")
        if self.allowed_repos and repo.lower() not in self.allowed_repos:
            raise GitHubError(403, f"Репозиторий {repo} не входит в список разрешённых")

    def _req(self, method: str, url: str, **kw) -> Any:
        if not self._token:
            raise GitHubError(401, "GitHub-токен не настроен на сервере")
        r = self.http.request(method, url, **kw)
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", r.text)
            except Exception:
                msg = r.text
            raise GitHubError(r.status_code, redact(str(msg))[:300])
        if r.status_code == 204 or not r.content:
            return None
        ct = r.headers.get("content-type", "")
        return r.json() if "json" in ct else r.content

    # --- репозитории
    def me(self) -> dict:
        return self._req("GET", "/user")

    def repo(self, repo: str) -> dict:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}")

    def create_repo(self, name: str, private: bool = True, description: str = "", org: str | None = None) -> dict:
        body = {"name": name, "private": private, "description": description, "auto_init": True}
        url = f"/orgs/{org}/repos" if org else "/user/repos"
        return self._req("POST", url, json=body)

    def tree(self, repo: str, ref: str) -> list[dict]:
        self.check_repo(repo)
        data = self._req("GET", f"/repos/{repo}/git/trees/{quote(ref, safe='')}", params={"recursive": "1"})
        return data.get("tree", [])

    def get_file(self, repo: str, path: str, ref: str) -> tuple[str, str] | None:
        self.check_repo(repo)
        try:
            d = self._req("GET", f"/repos/{repo}/contents/{quote(path)}", params={"ref": ref})
        except GitHubError as e:
            if e.status == 404:
                return None
            raise
        return base64.b64decode(d["content"]).decode("utf-8", "replace"), d["sha"]

    def branch_sha(self, repo: str, branch: str) -> str:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}/git/ref/heads/{quote(branch, safe='')}")["object"]["sha"]

    def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        self.check_repo(repo)
        self._req("POST", f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": from_sha})

    def create_file(self, repo: str, path: str, content: str, message: str, branch: str) -> dict:
        """Создать файл. Без sha GitHub откажет, если файл уже существует — перезапись невозможна."""
        self.check_repo(repo)
        body = {"message": message, "branch": branch,
                "content": base64.b64encode(content.encode()).decode()}
        return self._req("PUT", f"/repos/{repo}/contents/{quote(path)}", json=body)

    def update_file(self, repo: str, path: str, content: str, message: str, branch: str, sha: str) -> dict:
        self.check_repo(repo)
        body = {"message": message, "branch": branch, "sha": sha,
                "content": base64.b64encode(content.encode()).decode()}
        return self._req("PUT", f"/repos/{repo}/contents/{quote(path)}", json=body)

    def create_pr(self, repo: str, head: str, base: str, title: str, body: str) -> dict:
        self.check_repo(repo)
        return self._req("POST", f"/repos/{repo}/pulls", json={"head": head, "base": base, "title": title, "body": body})

    # --- PR и CI
    def list_prs(self, repo: str, state: str = "open") -> list[dict]:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}/pulls", params={"state": state, "per_page": 50})

    def get_pr(self, repo: str, number: int) -> dict:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}/pulls/{number}")

    def check_runs(self, repo: str, sha: str) -> list[dict]:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}/commits/{sha}/check-runs", params={"per_page": 100})["check_runs"]

    def combined_status(self, repo: str, sha: str) -> list[dict]:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}/commits/{sha}/status").get("statuses", [])

    def required_checks(self, repo: str, branch: str) -> list[str]:
        self.check_repo(repo)
        try:
            d = self._req("GET", f"/repos/{repo}/branches/{quote(branch, safe='')}/protection/required_status_checks")
        except GitHubError as e:
            if e.status in (403, 404):
                return []
            raise
        names = list(d.get("contexts") or [])
        names += [c["context"] for c in d.get("checks") or [] if c.get("context") not in names]
        return names

    def merge_pr(self, repo: str, number: int, sha: str, method: str = "squash", title: str | None = None) -> dict:
        self.check_repo(repo)
        body = {"sha": sha, "merge_method": method}
        if title:
            body["commit_title"] = title
        return self._req("PUT", f"/repos/{repo}/pulls/{number}/merge", json=body)

    def list_commits(self, repo: str, branch: str, n: int = 20) -> list[dict]:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}/commits", params={"sha": branch, "per_page": n})

    # --- Actions
    def workflow_runs(self, repo: str, n: int = 20) -> list[dict]:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}/actions/runs", params={"per_page": n})["workflow_runs"]

    def run(self, repo: str, run_id: int) -> dict:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}/actions/runs/{run_id}")

    def run_artifacts(self, repo: str, run_id: int) -> list[dict]:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}/actions/runs/{run_id}/artifacts")["artifacts"]

    def download_artifact(self, repo: str, artifact_id: int) -> bytes:
        self.check_repo(repo)
        return self._req("GET", f"/repos/{repo}/actions/artifacts/{artifact_id}/zip")

    def failed_jobs(self, repo: str, run_id: int) -> list[dict]:
        self.check_repo(repo)
        jobs = self._req("GET", f"/repos/{repo}/actions/runs/{run_id}/jobs")["jobs"]
        return [j for j in jobs if j.get("conclusion") not in ("success", "skipped", None)]
