#!/usr/bin/env python3
"""Keep sealed Android runners on their single, fully bound CI call site."""
import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_ROOT = ROOT / ".github" / "workflows"
VERIFY_WORKFLOW = (WORKFLOW_ROOT / "verify-v2.yml").read_text(encoding="utf-8")


def required_options(script_name):
    tree = ast.parse((ROOT / "tools" / script_name).read_text(encoding="utf-8"))
    options = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument" or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        if not first.value.startswith("--"):
            continue
        required = any(
            keyword.arg == "required"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        )
        if required:
            options.add(first.value)
    return options


class AndroidRunnerWorkflowContractTest(unittest.TestCase):
    def test_only_verify_v2_invokes_sealed_android_runners(self):
        workflows = sorted({
            *WORKFLOW_ROOT.glob("*.yml"),
            *WORKFLOW_ROOT.glob("*.yaml"),
        })
        for runner in (
            "tools/run_android_background_tests.py",
            "tools/run_android_diagnostics_tests.py",
        ):
            callers = [
                workflow.relative_to(ROOT).as_posix()
                for workflow in workflows
                if runner in workflow.read_text(encoding="utf-8")
            ]
            self.assertEqual(
                callers,
                [".github/workflows/verify-v2.yml"],
                "sealed runner must not be called by a legacy workflow: " + runner,
            )

    def test_background_runner_receives_every_required_binding(self):
        self.assert_runner_is_fully_bound(
            "run_android_background_tests.py",
            "Verify screen-off analysis and Activity-independent completion",
            "Verify crash trace recovery and diagnostic export to Downloads",
        )

    def test_diagnostics_runner_receives_every_required_binding(self):
        self.assert_runner_is_fully_bound(
            "run_android_diagnostics_tests.py",
            "Verify crash trace recovery and diagnostic export to Downloads",
            "Seal fresh Android instrumentation evidence",
        )

    def assert_runner_is_fully_bound(self, script_name, step_name, next_step_name):
        start = VERIFY_WORKFLOW.index("      - name: " + step_name)
        end = VERIFY_WORKFLOW.index("      - name: " + next_step_name, start + 1)
        body = VERIFY_WORKFLOW[start:end]
        invocation = "python3 tools/" + script_name
        self.assertEqual(body.count(invocation), 1, "canonical runner invocation is ambiguous")
        required = required_options(script_name)
        self.assertTrue(required, "runner must declare at least one required argument")
        passed = set(re.findall(r"(?<![A-Za-z0-9_])(--[a-z0-9-]+)\b", body))
        self.assertEqual(
            sorted(required - passed),
            [],
            "canonical runner invocation omits required binding(s)",
        )


if __name__ == "__main__":
    unittest.main()
