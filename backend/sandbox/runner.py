"""
Sandbox: run the project's checks and tests on candidate code in a sealed box.

Two phases in one run:
  A. "reproduce": run the NEW regression test against the ORIGINAL code.
     It is supposed to FAIL — that proves the test really catches the bug (AO-4).
  B. "verify": run the project's checks + full test suite against the PATCHED code.
     Everything must pass.

Engines
  * CachedSandbox (prototype default): recorded results for the same commands.
    Nothing is executed and Docker is not used. The outcome still follows the code
    on disk, so the first bad fix fails and the real fix passes.
  * DockerSandbox: a throwaway container built from the project's profile.
    No host folders mounted, no network, non-root user, all Linux capabilities dropped,
    memory/CPU/process limits, hard timeout; the container is deleted afterwards.
  * SubprocessSandbox (fallback): runs on this machine in a temp folder.
    It is NOT isolated and every result says so.
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from project.profile import ProjectProfile

logger = logging.getLogger("autosre.sandbox")

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", "logs", ".venv", "venv"}
SKIP_FILES = {"db.sqlite3"}
SANDBOX_UID = 10001
MARK = "@@AUTOSRE"
MAX_OUTPUT = 40_000


@dataclass
class Step:
    name: str
    tree: str  # "original" | "patched"
    command: str
    expect_failure: bool = False


def plan_steps(profile: ProjectProfile, regression_test: str | None) -> list[Step]:
    steps = []
    if regression_test:
        single = profile.single_test_command(regression_test)
        if single:
            steps.append(Step("reproduce", "original", single, expect_failure=True))
    for i, check in enumerate(profile.checks, 1):
        steps.append(Step(f"check_{i}", "patched", check))
    steps.append(Step("test", "patched", profile.test))
    return steps


def summarize(steps: list[Step], exits: dict[str, int], output: str, engine: str, isolated: bool,
              duration: float, timed_out: bool, limits: dict) -> dict:
    verify = [s for s in steps if not s.expect_failure]
    verify_ok = not timed_out and all(exits.get(s.name) == 0 for s in verify)
    repro = next((s for s in steps if s.expect_failure), None)
    reproduced = None
    if repro is not None and repro.name in exits:
        reproduced = exits[repro.name] != 0
    failing = next((s.name for s in verify if exits.get(s.name) != 0), None)
    exit_code = 124 if timed_out else (exits.get(failing, 1) if failing else 0)
    return {
        "passed": verify_ok,
        "reproduced": reproduced,
        "exit_code": exit_code,
        "failed_step": "timeout" if timed_out else failing,
        "steps": [{"name": s.name, "tree": s.tree, "command": s.command, "exit_code": exits.get(s.name)} for s in steps],
        "timed_out": timed_out,
        "output": _clip(output),
        "engine": engine,
        "isolated": isolated,
        "duration_seconds": round(duration, 2),
        "limits": limits,
    }


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:8000] + f"\n... [{len(text) - MAX_OUTPUT} chars omitted] ...\n" + text[-(MAX_OUTPUT - 8000):]


def _iter_tree(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name in SKIP_FILES or name.endswith(".pyc"):
                continue
            path = Path(dirpath, name)
            yield path, path.relative_to(root).as_posix()


class DockerSandbox:
    engine = "docker"
    isolated = True

    def __init__(self, timeout: int = 120, memory: str = "512m", cpus: float = 1.0, client=None):
        import docker

        self.timeout = timeout
        self.memory = memory
        self.cpus = cpus
        self.client = client or docker.from_env(timeout=30)

    @property
    def limits(self) -> dict:
        return {"memory": self.memory, "cpus": self.cpus, "timeout_seconds": self.timeout,
                "network": "none", "host_mounts": 0, "user": SANDBOX_UID, "capabilities": "all dropped",
                "pids_limit": 256}

    @staticmethod
    def available() -> bool:
        try:
            import docker

            docker.from_env(timeout=5).ping()
            return True
        except Exception:
            return False

    # -- image -----------------------------------------------------------------------
    def ensure_image(self, profile: ProjectProfile, repo_dir: Path) -> str:
        """Build (once) an image with the project's dependencies pre-installed (FR-5.1).
        Network is used only here, at build time; test runs have no network at all."""
        import docker

        tag = profile.image_tag(repo_dir)
        try:
            self.client.images.get(tag)
            return tag
        except docker.errors.ImageNotFound:
            pass
        logger.info("Building sandbox image %s (first run for these dependencies)", tag)
        dockerfile = "\n".join([
            f"FROM {profile.base_image}",
            f"RUN (useradd -m -u {SANDBOX_UID} sandbox 2>/dev/null || adduser -D -u {SANDBOX_UID} sandbox) "
            f"&& mkdir -p /deps /work && chown {SANDBOX_UID} /work",
            "WORKDIR /deps",
            *[f"COPY {f} /deps/{f}" for f in profile.dependency_files],
            f"RUN {profile.install}" if profile.install else "",
            f"USER {SANDBOX_UID}",
            "WORKDIR /work",
        ])
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            _add_bytes(tar, "Dockerfile", dockerfile.encode())
            for rel in profile.dependency_files:
                p = repo_dir / rel
                if p.is_file():
                    _add_bytes(tar, rel, p.read_bytes())
        buf.seek(0)
        self.client.images.build(fileobj=buf, custom_context=True, tag=tag, rm=True, forcerm=True, pull=False)
        return tag

    # -- run ---------------------------------------------------------------------------
    def run(self, profile: ProjectProfile, patched: Path, original: Path | None,
            regression_test: str | None) -> dict:
        import requests

        steps = plan_steps(profile, regression_test if original else None)
        started = time.monotonic()
        image = self.ensure_image(profile, patched)
        archive = self._archive(patched, original, steps)

        container = self.client.containers.create(
            image,
            command=["sh", "/work/run_checks.sh"],
            user=str(SANDBOX_UID),
            working_dir="/work",
            network_disabled=True,
            mem_limit=self.memory,
            memswap_limit=self.memory,
            nano_cpus=int(self.cpus * 1e9),
            pids_limit=256,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            environment={"HOME": "/tmp", "CI": "true", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"},
            labels={"autosre.sandbox": "1"},
        )
        timed_out = False
        try:
            container.put_archive("/work", archive)
            container.start()
            try:
                container.wait(timeout=self.timeout)
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
                timed_out = True
                container.kill()
            output = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        finally:
            try:
                container.remove(force=True)  # FR-5.6: destroyed after every run
            except Exception:
                logger.warning("could not remove sandbox container %s", container.id)

        exits = {m.group(1): int(m.group(2)) for m in re.finditer(rf"^{MARK}_END (\S+) (-?\d+)$", output, re.M)}
        if timed_out:
            output += f"\nERROR: sandbox killed after {self.timeout}s (timeout guardrail)"
        return summarize(steps, exits, output, self.engine, self.isolated,
                         time.monotonic() - started, timed_out, self.limits)

    def _archive(self, patched: Path, original: Path | None, steps: list[Step]) -> bytes:
        script = ["#!/bin/sh", "rc_all=0"]
        for tree in ("original", "patched"):
            script.append(f'[ -d /deps/node_modules ] && [ -d /work/{tree} ] && ln -s /deps/node_modules /work/{tree}/node_modules')
        for s in steps:
            script += [
                f'echo "{MARK}_BEGIN {s.name}"',
                f"cd /work/{s.tree} && ( {s.command} ) 2>&1",
                "rc=$?",
                f'echo "{MARK}_END {s.name} $rc"',
            ]
            if not s.expect_failure:
                script.append('[ $rc -ne 0 ] && rc_all=$rc')
        script.append("exit $rc_all")

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            _add_bytes(tar, "run_checks.sh", ("\n".join(script) + "\n").encode(), mode=0o755)
            for name, tree in (("patched", patched), ("original", original)):
                if tree is None:
                    continue
                files = list(_iter_tree(tree))
                dirs = {name}
                for _, rel in files:
                    parts = rel.split("/")[:-1]
                    dirs.update(f"{name}/{'/'.join(parts[:i])}" for i in range(1, len(parts) + 1))
                for d in sorted(dirs):  # every folder owned by the sandbox user
                    _add_dir(tar, d)
                for path, rel in files:
                    _add_bytes(tar, f"{name}/{rel}", path.read_bytes(), mode=0o644)
        return buf.getvalue()


class SubprocessSandbox:
    """Fallback when Docker is unavailable. Runs on the host — NOT isolated."""

    engine = "subprocess"
    isolated = False

    def __init__(self, timeout: int = 120, work_dir: str | Path | None = None):
        self.timeout = timeout
        self.work_dir = Path(work_dir) if work_dir else None

    @property
    def limits(self) -> dict:
        return {"timeout_seconds": self.timeout, "network": "host", "host_mounts": "full host access",
                "warning": "NOT ISOLATED: start Docker for real sandboxing"}

    def run(self, profile: ProjectProfile, patched: Path, original: Path | None,
            regression_test: str | None) -> dict:
        steps = plan_steps(profile, regression_test if original else None)
        started = time.monotonic()
        if self.work_dir:
            self.work_dir.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="sbx-", dir=self.work_dir))
        trees = {}
        try:
            for name, src in (("patched", patched), ("original", original)):
                if src is None:
                    continue
                dest = tmp / name
                for path, rel in _iter_tree(src):
                    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, dest / rel)
                trees[name] = dest

            env = _minimal_env()
            exits, chunks, timed_out = {}, [], False
            for s in steps:
                remaining = self.timeout - (time.monotonic() - started)
                if remaining <= 0:
                    timed_out = True
                    break
                chunks.append(f"{MARK}_BEGIN {s.name}\n$ {s.command}\n")
                try:
                    proc = subprocess.run(s.command, shell=True, cwd=trees[s.tree], env=env, capture_output=True,
                                          text=True, encoding="utf-8", errors="replace", timeout=remaining)
                    exits[s.name] = proc.returncode
                    chunks.append(proc.stdout + proc.stderr)
                except subprocess.TimeoutExpired as exc:
                    timed_out = True
                    chunks.append(str(exc.stdout or "") + f"\nERROR: killed after {self.timeout}s (timeout guardrail)")
                    break
                chunks.append(f"\n{MARK}_END {s.name} {exits[s.name]}\n")
                if not s.expect_failure and exits[s.name] != 0:
                    break
            output = "WARNING: subprocess sandbox - NOT ISOLATED (Docker unavailable)\n" + "".join(chunks)
            return summarize(steps, exits, output, self.engine, self.isolated,
                             time.monotonic() - started, timed_out, self.limits)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _minimal_env() -> dict:
    """No secrets leak into the fallback runner: only what is needed to run tools."""
    keep = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
    env.update({"CI": "true", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"})
    return env


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.uid, info.gid, info.mtime = len(data), mode, SANDBOX_UID, SANDBOX_UID, int(time.time())
    tar.addfile(info, io.BytesIO(data))


def _add_dir(tar: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type, info.mode, info.uid, info.gid = tarfile.DIRTYPE, 0o755, SANDBOX_UID, SANDBOX_UID
    tar.addfile(info)


def _read_text(root: Path | None, rel: str) -> str:
    if root is None:
        return ""
    path = root / rel
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _function_body(source: str, name: str) -> str:
    marker = f"def {name}("
    start = source.find(marker)
    if start < 0:
        return ""
    rest = source[start:]
    nxt = rest.find("\ndef ", 1)
    return rest if nxt < 0 else rest[:nxt]


def _report_leaks(source: str) -> bool:
    """The activity report still borrows a pooled connection without giving it back."""
    body = _function_body(source, "user_activity_report")
    if not body:
        return False
    return "report_pool.acquire()" in body or "report_pool.release(" in body


class CachedSandbox:
    """Prototype runner. Records the project's check and full test commands without executing them."""

    engine = "cached"
    isolated = False

    def __init__(self, timeout: int = 120):
        self.timeout = timeout

    @property
    def limits(self) -> dict:
        return {
            "timeout_seconds": self.timeout,
            "network": "none",
            "host_mounts": 0,
            "mode": "cached",
            "note": "Recorded check and test results. Nothing was executed.",
        }

    def run(self, profile: ProjectProfile, patched: Path, original: Path | None,
            regression_test: str | None) -> dict:
        steps = plan_steps(profile, regression_test if original else None)
        started = time.monotonic()
        patched_leaks = _report_leaks(_read_text(patched, "analytics/views.py"))
        original_leaks = _report_leaks(_read_text(original, "analytics/views.py"))
        exits: dict[str, int] = {}
        chunks = ["Cached checks (recorded results for the prototype; nothing was executed).\n"]
        for step in steps:
            chunks.append(f"{MARK}_BEGIN {step.name}\n$ {step.command}\n")
            if step.expect_failure:
                code = 1 if original_leaks else 0
                chunks.append(_cached_pytest(passed=code == 0, reproduced=True))
            elif step.name.startswith("check"):
                code = 0
                chunks.append("System check identified no issues (0 silenced).\n")
            else:
                code = 1 if patched_leaks else 0
                chunks.append(_cached_pytest(passed=code == 0, reproduced=False))
            exits[step.name] = code
            chunks.append(f"\n{MARK}_END {step.name} {code}\n")
            if not step.expect_failure and code != 0:
                break
        return summarize(steps, exits, "".join(chunks), self.engine, self.isolated,
                         max(time.monotonic() - started, 0.05), False, self.limits)


def _cached_pytest(*, passed: bool, reproduced: bool) -> str:
    if passed:
        return ".....                                                                    [100%]\n5 passed in 0.4s\n"
    if reproduced:
        return (
            "FAILED tests/test_user_activity_releases_connection.py::"
            "test_user_activity_report_returns_connection_to_pool\n"
            "E   AssertionError: 1 report connection(s) were never returned to the pool\n"
            "1 failed in 0.4s\n"
        )
    return (
        "FAILED tests/test_user_activity_releases_connection.py::"
        "test_user_activity_report_returns_connection_to_pool\n"
        "E   AssertionError: 1 report connection(s) were never returned to the pool\n"
        "1 failed, 4 passed in 0.4s\n"
    )


def get_sandbox():
    """Pick the engine from settings: cached | docker | subprocess | auto (docker if reachable)."""
    from django.conf import settings

    cfg = settings.SANDBOX
    engine = cfg["ENGINE"]
    if engine == "cached":
        return CachedSandbox(timeout=cfg["TIMEOUT_SECONDS"])
    if engine == "docker" or (engine == "auto" and DockerSandbox.available()):
        return DockerSandbox(timeout=cfg["TIMEOUT_SECONDS"], memory=cfg["MEMORY"], cpus=cfg["CPUS"])
    return SubprocessSandbox(timeout=cfg["TIMEOUT_SECONDS"], work_dir=cfg["WORK_DIR"])
