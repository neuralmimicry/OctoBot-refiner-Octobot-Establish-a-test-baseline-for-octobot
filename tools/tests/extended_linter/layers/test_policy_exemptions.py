import unittest

import tools.extended_linter.config.loader as config_loader
import tools.extended_linter.layers.diff_policy as layer_diff
import tools.extended_linter.layers.path_policy as layer_path


def added_line(path, content):
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n+{content}\n"


class TestReviewedPolicyExemptions(unittest.TestCase):
    def test_negative_fixtures_do_not_exempt_runtime_or_other_rules(self):
        policy = config_loader.load_policy()
        examples = {
            "diff.no_pip_install": "pip install unexpected-library",
            "diff.no_npm_install": "npm install unexpected-library",
            "diff.no_git_force_push": "git push --force origin main",
            "diff.no_subprocess_pip": 'subprocess.run(["pip", "install", "unexpected-library"])',
            "diff.no_disable_verify": "git commit --no-verify",
            "diff.no_bare_except": "except:",
        }
        for rule_id, snippet in examples.items():
            with self.subTest(rule=rule_id):
                runtime = layer_diff.run(added_line("octobot/runtime.py", snippet), policy)
                self.assertIn(rule_id, {violation.rule_id for violation in runtime})
                fixture = layer_diff.run(
                    added_line("tools/tests/extended_linter/fixture.py", snippet), policy,
                )
                self.assertNotIn(rule_id, {violation.rule_id for violation in fixture})
        # Exemption applies to each listed rule, not the entire file.
        violations = layer_diff.run(
            added_line(".github/workflows/main.yml", "except:"), policy,
        )
        self.assertIn("diff.no_bare_except", {violation.rule_id for violation in violations})

    def test_only_the_existing_placeholder_template_is_exempt_from_dotenv_deny(self):
        policy = config_loader.load_policy()
        violations = layer_path.run([
            "additional_tests/exchanges_tests/.env.template", ".env",
            "additional_tests/exchanges_tests/.env.production",
            "octobot/.env.template",
        ], policy)
        denied = {violation.file for violation in violations if violation.rule_id == "path.deny_dotenv"}
        self.assertEqual(denied, {
            ".env", "additional_tests/exchanges_tests/.env.production", "octobot/.env.template",
        })

    def test_rule_definition_is_not_a_subprocess_execution(self):
        policy = config_loader.load_policy()
        violations = layer_diff.run(added_line(
            "tools/extended_linter/config/policy.yaml", "- rule_id: diff.no_subprocess_pip",
        ), policy)
        self.assertNotIn("diff.no_subprocess_pip", {violation.rule_id for violation in violations})
