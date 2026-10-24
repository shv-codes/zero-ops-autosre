#!/usr/bin/env python3
"""
One-time (and re-runnable) setup for AutoSRE on Windows, macOS or Linux.

    python scripts/setup.py           # prototype: no Docker
    python scripts/setup.py --docker  # also start Postgres, the victim, and a sandbox image

Steps: check tools -> .venv + backend deps -> .env -> database -> seed victim repo ->
frontend deps. Docker is optional and only runs with --docker.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def step(msg: str) -> None:
    print(f"\n==> {msg}")


def run(cmd: list[str], cwd: Path = ROOT, check: bool = True) -> int:
    print("   $", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=cwd, check=check, shell=(os.name == "nt" and cmd[0] in ("npm", "npx"))).returncode


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def docker_running() -> bool:
    return have("docker") and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--docker", action="store_true",
                        help="start PostgreSQL, the victim service, and build the sandbox image")
    parser.add_argument("--no-docker", action="store_true",
                        help="ignored; Docker is skipped unless --docker is passed")
    parser.add_argument("--reseed", action="store_true", help="recreate the victim git history")
    args = parser.parse_args()

    step("Checking tools")
    if sys.version_info < (3, 11):
        sys.exit("Python 3.11+ is required")
    git_version = subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    print(f"   python {sys.version.split()[0]} | {git_version} | node {'yes' if have('node') else 'MISSING'} | "
          f"docker {'running' if docker_running() else 'not running'}")

    step("Python environment (.venv) and backend dependencies")
    if not PY.exists():
        run([sys.executable, "-m", "venv", str(VENV)])
    run([str(PY), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    run([str(PY), "-m", "pip", "install", "--quiet", "-r", "backend/requirements.txt"])

    step(".env")
    if not (ROOT / ".env").exists():
        shutil.copy(ROOT / ".env.example", ROOT / ".env")
        print("   created .env from .env.example (add GROQ_API_KEY / GITHUB_TOKEN later for live mode)")
    else:
        print("   .env already exists")

    step("AutoSRE database")
    run([str(PY), "backend/manage.py", "migrate", "--noinput", "-v", "0"])

    step("Victim git history (var/victim_origin.git + var/victim_repo)")
    if args.reseed or not (ROOT / "var" / "victim_origin.git").exists():
        run([str(PY), "scripts/seed_victim_repo.py", "--force"])
    else:
        print("   already seeded (use --reseed to recreate)")

    step("Frontend dependencies")
    if have("npm"):
        run(["npm", "install", "--no-audit", "--no-fund"], cwd=ROOT / "frontend")
    else:
        print("   npm not found: install Node.js 18+ to run the dashboard")

    if not args.docker or args.no_docker:
        print("\nPrototype mode: skipping Docker. Checks are cached, so no container is required.")
        print("   Re-run with --docker to start PostgreSQL, the victim service, and a sandbox image.")
    elif not docker_running():
        print("\n!! Docker is not running. Start Docker Desktop, then re-run with --docker.")
    else:
        step("Starting PostgreSQL + victim service (docker compose)")
        run(["docker", "compose", "up", "-d", "--build"])
        step("Building the sandbox image for the victim project (one time; later runs are cached)")
        run([str(PY), "-c", (
            "import os,sys; sys.path.insert(0,'backend'); os.environ.setdefault('DJANGO_SETTINGS_MODULE','autosre_api.settings');"
            "import django; django.setup();"
            "from pathlib import Path; from project.profile import load_profile; from sandbox.runner import DockerSandbox;"
            "repo=Path('var/victim_repo'); print('   image:', DockerSandbox().ensure_image(load_profile(repo), repo))"
        )])

    print("\nDone. Start everything with:  python scripts/dev.py   then open http://127.0.0.1:5173")


if __name__ == "__main__":
    main()
