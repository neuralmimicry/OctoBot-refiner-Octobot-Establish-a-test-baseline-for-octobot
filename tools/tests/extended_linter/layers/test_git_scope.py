import pathlib
import subprocess
import tempfile
import unittest

import mock

import tools.extended_linter.layers.git_scope as layer_git


class TestVerifyMergeBase(unittest.TestCase):
    def test_missing_ref_violation(self) -> None:
        with mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(returncode=1, stderr="bad ref")
            violations = layer_git.verify_merge_base(
                pathlib.Path("."),
                "origin/dev",
                {"git_rules": [{"rule_id": "git.merge_base_missing", "hint": "fetch"}]},
            )
        self.assertEqual(violations[0].rule_id, "git.merge_base_missing")

    def test_existing_ref_without_shared_shallow_history_is_a_violation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = pathlib.Path(directory) / "source"
            shallow = pathlib.Path(directory) / "shallow"
            source.mkdir()
            def git(*args, cwd=source):
                return subprocess.run(
                    ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                )
            git("init")
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "--allow-empty", "-m", "base")
            base = git("rev-parse", "HEAD").stdout.strip()
            git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                "commit", "--allow-empty", "-m", "head")
            git("clone", "--depth=1", source.as_uri(), str(shallow))
            git("fetch", "--depth=1", str(source), base, cwd=shallow)
            git("update-ref", "refs/remotes/origin/base", base, cwd=shallow)
            # Resolving the ref alone succeeds, as in the original CI job.
            git("rev-parse", "--verify", "origin/base", cwd=shallow)
            violations = layer_git.verify_merge_base(shallow, "origin/base", {})
            self.assertEqual(violations[0].rule_id, "git.merge_base_missing")
            with self.assertRaises(RuntimeError):
                layer_git.list_changed_paths(shallow, "origin/base")
