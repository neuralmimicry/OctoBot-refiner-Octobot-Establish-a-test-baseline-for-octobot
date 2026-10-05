#!/usr/bin/env python3
"""Apply the NeuralMimicry OctoBot overlay (ordered patch queue) to an upstream tree.

    apply.py [--target DIR] [--skip-tag TAG ...] [--check] [--no-3way] [--strict]

Guarantees
  * Idempotent: if the whole queue is already applied (every patch reverses
    cleanly, last to first) nothing is written and "UNCHANGED" is printed.
  * Never half-applies: the files touched by the queue are copied to a private
    git staging repo, the queue is applied and verified there (compile() for
    .py, json for .json), and only then are the results swapped into TARGET
    file-by-file with atomic renames.
  * Fails loudly: the first patch that neither applies nor is already present
    aborts the run (exit 1) with git's error, the conflicting hunks and, when
    a 3-way merge was attempted, the conflict markers. TARGET is not modified.

A patch whose change is already present in TARGET (e.g. adopted upstream) is
reported as ALREADY-PRESENT and skipped; --strict turns that into an error.
When TARGET is a git checkout that contains the patch's preimage blobs, a
patch that no longer applies exactly is retried with `git apply --3way`; a
clean 3-way result is accepted with a REFRESH warning (regenerate the patch),
a conflicting one aborts.

Exit codes: 0 applied/unchanged, 1 conflict or verification failure, 2 usage.
Output last line: UPDATED | UNCHANGED | (CHECK-OK with --check).

Maintenance after an upstream bump: run with --target on a fresh checkout of
the new upstream ref; fix any reported patch (or use ./export.sh to rebuild
the queue from a branch with one commit per patch), update UPSTREAM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def read_series(skip_tags: set[str]) -> list[tuple[Path, list[str]]]:
    series = []
    for raw in (HERE / "series").read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name, *tags = line.split()
        path = HERE / name
        if not path.is_file():
            die(f"series entry {name} does not exist")
        if skip_tags.intersection(tags):
            print(f"SKIP-TAG {name} ({' '.join(tags)})")
            continue
        series.append((path, tags))
    return series


DIFF_HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.M)


def touched_paths(series) -> list[str]:
    paths: list[str] = []
    for patch, _ in series:
        for a, b in DIFF_HEADER.findall(patch.read_text()):
            for p in (a, b):
                if p not in paths:
                    paths.append(p)
    return paths


def git(args, cwd, check=False, env=None):
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True, env=env)
    if check and proc.returncode != 0:
        die(f"git {' '.join(args)} failed:\n{proc.stderr}")
    return proc


class Stage:
    """A throwaway git repo holding copies of the touched files."""

    def __init__(self, target: Path, paths: list[str]):
        self.root = Path(tempfile.mkdtemp(prefix="octobot-overlay-"))
        self.env = {**os.environ, "GIT_AUTHOR_NAME": "overlay", "GIT_AUTHOR_EMAIL": "overlay@localhost",
                    "GIT_COMMITTER_NAME": "overlay", "GIT_COMMITTER_EMAIL": "overlay@localhost"}
        git(["init", "-q", "."], self.root, check=True)
        target_git = git(["rev-parse", "--git-common-dir"], target)
        self.has_objects = False
        if target_git.returncode == 0:
            objects = (target / target_git.stdout.strip() / "objects").resolve()
            if objects.is_dir():
                (self.root / ".git/objects/info/alternates").write_text(f"{objects}\n")
                self.has_objects = True
        self.paths = paths
        for rel in paths:
            src = target / rel
            if src.is_file():
                dst = self.root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        git(["add", "-A"], self.root, check=True)
        git(["commit", "-q", "--allow-empty", "-m", "target"], self.root, check=True, env=self.env)

    def apply(self, patch: Path, *extra: str):
        return git(["apply", "--index", "--whitespace=nowarn", *extra, str(patch)], self.root)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def show_hunks(patch: Path, stderr: str) -> str:
    """Return the hunks of the files git complained about."""
    text = patch.read_text()
    files = set(re.findall(r"patch failed: ([^:]+):\d+", stderr)) | set(
        re.findall(r"error: ([^:]+): does not exist in index", stderr))
    out = []
    for block in re.split(r"(?=^diff --git )", text, flags=re.M):
        m = DIFF_HEADER.match(block)
        if m and (not files or m.group(2) in files):
            out.append(block.rstrip())
    return "\n".join(out)


def verify(stage: Stage) -> None:
    for rel in stage.paths:
        f = stage.root / rel
        if not f.is_file():
            continue
        if f.suffix == ".py":
            try:
                compile(f.read_bytes(), str(rel), "exec", dont_inherit=True)
            except SyntaxError as err:
                die(f"verification failed, {rel} does not compile: {err}")
        elif f.suffix == ".json":
            try:
                json.loads(f.read_text())
            except ValueError as err:
                die(f"verification failed, {rel} is not valid JSON: {err}")


def fully_applied(stage: Stage, series) -> bool:
    for patch, _ in reversed(series):
        if stage.apply(patch, "-R").returncode != 0:
            git(["reset", "-q", "--hard"], stage.root)
            return False
    git(["reset", "-q", "--hard"], stage.root)
    return True


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def swap_in(stage: Stage, target: Path) -> int:
    changed = 0
    for rel in stage.paths:
        src, dst = stage.root / rel, target / rel
        if digest(src) == digest(dst):
            continue
        if not src.is_file():
            die(f"patch queue deletes {rel}; deletions are not supported")
        dst.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{dst.name}.", dir=dst.parent)
        os.close(fd)
        shutil.copyfile(src, tmp)
        mode = dst.stat().st_mode & 0o7777 if dst.exists() else 0o644
        os.chmod(tmp, mode)
        os.replace(tmp, dst)
        changed += 1
    return changed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", default=".", help="OctoBot source tree (default: cwd)")
    ap.add_argument("--skip-tag", action="append", default=[], help="skip patches carrying TAG")
    ap.add_argument("--check", action="store_true", help="verify only, never write TARGET")
    ap.add_argument("--no-3way", action="store_true", help="never fall back to git apply --3way")
    ap.add_argument("--strict", action="store_true", help="treat ALREADY-PRESENT patches as errors")
    args = ap.parse_args()

    target = Path(args.target).resolve()
    if not (target / "packages").is_dir() or not (target / "pants.toml").is_file():
        die(f"{target} does not look like an OctoBot source tree", 2)
    series = read_series(set(args.skip_tag))
    stage = Stage(target, touched_paths(series))
    try:
        if fully_applied(stage, series):
            print(f"overlay already applied ({len(series)} patches)")
            print("CHECK-OK" if args.check else "UNCHANGED")
            return
        applied = present = 0
        for patch, _ in series:
            name = patch.name
            res = stage.apply(patch)
            if res.returncode == 0:
                applied += 1
                print(f"APPLIED {name}")
                continue
            if stage.apply(patch, "-R", "--check").returncode == 0:
                if args.strict:
                    die(f"{name} is already present in the target (--strict)")
                present += 1
                print(f"ALREADY-PRESENT {name} (adopted upstream? drop or refresh the patch)")
                continue
            if stage.has_objects and not args.no_3way:
                res3 = stage.apply(patch, "--3way")
                if res3.returncode == 0:
                    applied += 1
                    print(f"APPLIED {name} via 3-way merge -- REFRESH this patch against the new upstream")
                    continue
                conflicts = git(["diff"], stage.root).stdout
                die(f"{name} conflicts with the target tree (3-way merge failed).\n"
                    f"git apply:\n{res.stderr}{res3.stderr}\nconflict markers:\n{conflicts}\n"
                    f"patch hunks:\n{show_hunks(patch, res.stderr)}\n"
                    f"TARGET {target} was not modified.")
            die(f"{name} does not apply to the target tree.\n"
                f"git apply:\n{res.stderr}\npatch hunks:\n{show_hunks(patch, res.stderr)}\n"
                f"TARGET {target} was not modified.")
        verify(stage)
        if args.check:
            print(f"would apply {applied} patches ({present} already present)")
            print("CHECK-OK")
            return
        changed = swap_in(stage, target)
        print(f"applied {applied} patches ({present} already present), {changed} files written")
        print("UPDATED" if changed else "UNCHANGED")
    finally:
        stage.cleanup()


if __name__ == "__main__":
    main()
