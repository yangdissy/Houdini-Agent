import json
from pathlib import Path

import pytest

from tests.integration.houdini_runner import IsolatedProcessRunner


pytestmark = pytest.mark.houdini_integration

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_SCRIPT = Path(__file__).parent / "houdini_scenarios.py"


@pytest.mark.parametrize(
    "scenario",
    [
        "mutation_undo", "update_mode_restore", "hip_save_reload",
        "schema_handler_contract", "failure_recovery",
    ],
)
def test_real_houdini_scenario(hython_executable, tmp_path, scenario):
    runner = IsolatedProcessRunner(tmp_path / "houdini-artifacts", timeout=120.0)
    result_relative = Path("result.json")

    run = runner.run(
        hython_executable,
        [
            str(SCENARIO_SCRIPT),
            scenario,
            "--result", str(result_relative),
        ],
        repository_root=REPO_ROOT,
    )

    assert run.status == "passed", (
        f"{scenario} failed; artifacts: {run.artifact_dir}\n{run.stderr}"
    )
    assert run.artifact_dir is None


def test_package_and_hda_are_loaded_from_isolated_directories(
    hython_executable, tmp_path
):
    runner = IsolatedProcessRunner(tmp_path / "houdini-artifacts", timeout=120.0)
    package_dir = tmp_path / "test-packages"
    package_dir.mkdir()
    (package_dir / "isolated_test.json").write_text(
        json.dumps({
            "env": [{"HOUDINI_TEST_PACKAGE_MARKER": "isolated-package-loaded"}]
        }),
        encoding="utf-8",
    )

    run = runner.run(
        hython_executable,
        [str(SCENARIO_SCRIPT), "package_hda_isolation", "--result", "result.json"],
        repository_root=REPO_ROOT,
        extra_env={"HOUDINI_PACKAGE_DIR": str(package_dir)},
    )

    assert run.status == "passed", (
        f"package_hda_isolation failed; artifacts: {run.artifact_dir}\n{run.stderr}"
    )
    assert run.artifact_dir is None
