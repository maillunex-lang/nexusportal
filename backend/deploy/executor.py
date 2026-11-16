"""Исполнители команд развёртывания: SSH к одному VPS или локально (портал на том же VPS)."""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from ..core import app_settings
from ..core.redact import redact


class ExecError(RuntimeError):
    pass


class LocalExecutor:
    """Выполняет bash-скрипт локально. Используется, если портал и проекты на одном VPS, и в тестах."""

    name = "local"

    def run(self, script: str, timeout: int = 900) -> tuple[int, str]:
        p = subprocess.run(["bash", "-s"], input=script.encode(), capture_output=True, timeout=timeout)
        return p.returncode, redact((p.stdout + p.stderr).decode("utf-8", "replace"))[-20000:]

    def upload(self, local: Path, remote: str) -> None:
        p = subprocess.run(["install", "-D", "-m", "0644", str(local), remote], capture_output=True)
        if p.returncode != 0:
            raise ExecError(p.stderr.decode()[:500])


class SSHExecutor:
    """Прямой SSH к VPS. Проверка ключа хоста обязательна, пароли не используются."""

    name = "ssh"

    def __init__(self, host: str, user: str, port: int, key: Path, known_hosts: Path):
        if not host or not user:
            raise ExecError("SSH не настроен: укажите хост и пользователя в настройках")
        if not key or not Path(key).exists():
            raise ExecError("SSH-ключ не найден на сервере (NEXUS_SSH_KEY)")
        if not known_hosts or not Path(known_hosts).exists():
            raise ExecError("Файл known_hosts не найден (NEXUS_SSH_KNOWN_HOSTS)")
        self.host, self.user, self.port = host, user, int(port)
        self.opts = ["-i", str(key), "-p", str(self.port), "-o", "BatchMode=yes",
                     "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_hosts}",
                     "-o", "ConnectTimeout=15", "-o", "IdentitiesOnly=yes"]

    def run(self, script: str, timeout: int = 900) -> tuple[int, str]:
        p = subprocess.run(["ssh", *self.opts, f"{self.user}@{self.host}", "bash -s"],
                           input=script.encode(), capture_output=True, timeout=timeout)
        return p.returncode, redact((p.stdout + p.stderr).decode("utf-8", "replace"))[-20000:]

    def upload(self, local: Path, remote: str) -> None:
        code, out = self.run(f"mkdir -p {shlex.quote(str(Path(remote).parent))}")
        if code:
            raise ExecError(out)
        scp_opts = [o if o != "-p" else "-P" for o in self.opts]
        p = subprocess.run(["scp", "-q", *scp_opts, str(local), f"{self.user}@{self.host}:{remote}"],
                           capture_output=True, timeout=900)
        if p.returncode != 0:
            raise ExecError(redact(p.stderr.decode()[:500]))


def make_executor(portal, project: dict, env: str):
    kind = app_settings.get(portal.db, "deploy_executor")
    if kind == "local":
        return LocalExecutor()
    s = portal.settings
    return SSHExecutor(app_settings.get(portal.db, "ssh_host"), app_settings.get(portal.db, "ssh_user"),
                       app_settings.get(portal.db, "ssh_port") or 22, s.ssh_key_path, s.ssh_known_hosts)
