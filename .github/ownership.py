#!/usr/bin/env python3
"""PR lane check: every changed file must be inside the PR author's lane, the branch must carry
the author's prefix, and (if configured) every commit must be authored by the lane owner.

Runs in CI (see workflows/ownership.yml). Reads .github/OWNERS.json.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

cfg = json.loads(Path(".github/OWNERS.json").read_text())
login = os.environ["AUTHOR"]
base, head = os.environ["BASE"], os.environ["HEAD"]
branch = os.environ.get("HEAD_REF", "")

lane = cfg["logins"].get(login)
if lane is None:
    print(f"::error::GitHub login '{login}' is not in .github/OWNERS.json. Add it under 'logins'.")
    sys.exit(1)
spec = cfg["lanes"][lane]
allowed = list(spec["paths"]) + list(cfg["shared_for_everyone"]) + [f"{cfg['own_log_prefix']}{lane}.md"]

changed = subprocess.run(["git", "diff", "--name-only", f"{base}...{head}"], capture_output=True, text=True, check=True).stdout.split()
bad = [f for f in changed if not any(f.startswith(p) for p in allowed)]
ok = True
if bad:
    ok = False
    print(f"::error::PR by {login} ({lane}) touches files outside the lane:")
    for f in bad:
        print(f"   {f}")
    print(f"Allowed prefixes: {allowed}")

if branch and not branch.startswith(f"{lane}/"):
    ok = False
    print(f"::error::Branch '{branch}' must start with '{lane}/' for PRs opened by {login}.")

authors = spec.get("authors") or []
if authors:
    emails = subprocess.run(["git", "log", "--format=%ae", f"{base}..{head}"], capture_output=True, text=True, check=True).stdout.split()
    foreign = sorted({e for e in emails if e not in authors})
    if foreign:
        ok = False
        print(f"::error::Commits by non-owners on a {lane} branch: {foreign}. Only {authors} may commit here.")

print("ownership: OK" if ok else "ownership: FAILED")
sys.exit(0 if ok else 1)
