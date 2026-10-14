from pathlib import Path
import sys

from tests.integration.houdini_runner import IsolatedProcessRunner


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER = Path(__file__).parent / "fixtures" / "isolated_process_worker.py"


def test_success_cleans_run_directory(tmp_path):
    runner = IsolatedProcessRunner(tmp_path / "failures", timeout=5.0)

    result = runner.run(
        Path(sys.executable), [str(WORKER), "success"],
        repository_root=REPO_ROOT,
    )

    assert result.status == "passed"
    assert result.artifact_dir is None
    assert not (tmp_path / "failures").exists()


def test_failure_preserves_logs_manifest_and_isolated_environment(tmp_path):
    runner = IsolatedProcessRunner(tmp_path / "failures", timeout=5.0)

    result = runner.run(
        Path(sys.executable), [str(WORKER), "fail"],
        repository_root=REPO_ROOT,
    )

    assert result.status == "failed"
    assert result.exit_code == 7
    assert result.artifact_dir is not None
    environment = __import__("json").loads(
        (result.artifact_dir / "artifacts" / "environment.json").read_text("utf-8")
    )
    Path(environment["home"]).relative_to(result.artifact_dir)
    Path(environment["prefs"]).relative_to(result.artifact_dir)
    Path(environment["hip"]).relative_to(result.artifact_dir)
    assert Path(environment["cwd"]) == result.artifact_dir / "artifacts"
    assert (result.artifact_dir / "manifest.json").is_file()
    assert (result.artifact_dir / "stdout.log").is_file()
    assert (result.artifact_dir / "stderr.log").is_file()


def test_timeout_preserves_artifacts(tmp_path):
    runner = IsolatedProcessRunner(tmp_path / "failures", timeout=0.1)

    result = runner.run(
        Path(sys.executable), [str(WORKER), "hang"],
        repository_root=REPO_ROOT,
    )

    assert result.status == "timeout"
    assert result.artifact_dir is not None
    assert (result.artifact_dir / "manifest.json").is_file()
