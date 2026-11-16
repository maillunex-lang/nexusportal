"""Проверка релизного артефакта: метаданные, контрольная сумма, SHA, подпись APK."""
from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,3}([-+][A-Za-z0-9.]+)?$")
FORBIDDEN_NAME = re.compile(r"(?i)(debug|unsigned|test)")
APK_SIG_MAGIC = b"APK Sig Block 42"


class ReleaseError(ValueError):
    pass


@dataclass
class VerifiedRelease:
    version: str
    version_code: int | None
    file_name: str
    sha256: str
    size: int
    content: bytes
    metadata: dict


def _safe_name(name: str) -> str:
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$", name):
        raise ReleaseError(f"Недопустимое имя файла: {name!r}")
    return name


def apk_signature_ok(data: bytes) -> tuple[bool, str]:
    """Есть ли у APK подпись (v2+ или v1) и не является ли она отладочной."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return False, "APK повреждён"
    names = z.namelist()
    if "AndroidManifest.xml" not in names:
        return False, "Нет AndroidManifest.xml"
    v1 = [n for n in names if re.match(r"^META-INF/[^/]+\.(RSA|DSA|EC)$", n)]
    v2 = APK_SIG_MAGIC in data
    if not v1 and not v2:
        return False, "APK не подписан"
    blobs = [z.read(n) for n in v1]
    if v2:
        blobs.append(data)
    if any(b"Android Debug" in b for b in blobs):
        return False, "APK подписан отладочным ключом"
    if shutil.which("apksigner"):
        with tempfile.NamedTemporaryFile(suffix=".apk") as f:
            f.write(data)
            f.flush()
            p = subprocess.run(["apksigner", "verify", f.name], capture_output=True)
            if p.returncode != 0:
                return False, "apksigner: подпись недействительна"
    return True, "ok"


def verify_artifact(zip_bytes: bytes, expected_sha: str) -> VerifiedRelease:
    """Артефакт релизного CI — zip с файлами:

    release.json  {"version","version_code","channel":"release","sha","file"}
    SHA256SUMS    строки «<sha256>  <файл>»
    <file>        сам релиз (APK, zip веб-сборки и т.п.)
    """
    try:
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise ReleaseError("Артефакт не является zip-архивом")
    names = set(z.namelist())
    if "release.json" not in names:
        raise ReleaseError("В артефакте нет release.json")
    if "SHA256SUMS" not in names:
        raise ReleaseError("В артефакте нет SHA256SUMS")
    try:
        meta = json.loads(z.read("release.json"))
    except ValueError:
        raise ReleaseError("release.json повреждён")
    if meta.get("channel") != "release":
        raise ReleaseError("Канал сборки не release — тестовые сборки не публикуются")
    version = str(meta.get("version", ""))
    if not VERSION_RE.match(version):
        raise ReleaseError(f"Некорректная версия: {version!r}")
    if not expected_sha or meta.get("sha") != expected_sha:
        raise ReleaseError("SHA в release.json не совпадает с SHA релизного запуска CI")
    fname = _safe_name(str(meta.get("file", "")))
    if FORBIDDEN_NAME.search(fname):
        raise ReleaseError("Имя файла указывает на тестовую или неподписанную сборку")
    if fname not in names:
        raise ReleaseError(f"Файл {fname} отсутствует в артефакте")
    content = z.read(fname)
    digest = hashlib.sha256(content).hexdigest()
    sums = {}
    for line in z.read("SHA256SUMS").decode().splitlines():
        parts = line.strip().split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0].lower()
    if sums.get(fname) != digest:
        raise ReleaseError("Контрольная сумма SHA-256 не совпадает")
    if fname.lower().endswith(".apk"):
        ok, why = apk_signature_ok(content)
        if not ok:
            raise ReleaseError(why)
    code = meta.get("version_code")
    return VerifiedRelease(version, int(code) if code is not None else None, fname, digest,
                           len(content), content, meta)


def write_release_dir(rel: VerifiedRelease, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / rel.file_name).write_bytes(rel.content)
    (dest / "SHA256SUMS").write_text(f"{rel.sha256}  {rel.file_name}\n")
    (dest / "release.json").write_text(json.dumps(rel.metadata, ensure_ascii=False, indent=2))
    return dest
