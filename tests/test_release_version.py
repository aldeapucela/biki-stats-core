from scripts import release_version
from scripts.release_version import highest_bump, next_version


def test_breaking_commit_has_priority() -> None:
    commits = [
        "fix: corregir respuesta",
        "feat(api)!: cambiar contrato\n\nBREAKING CHANGE: cambia el formato",
    ]
    assert highest_bump(commits) == "major"


def test_feature_and_patch_commits_bump_minor() -> None:
    assert next_version("0.1.0", ["fix: corregir captura", "feat: añadir proveedor"]) == "0.2.0"


def test_non_release_commits_do_not_create_version() -> None:
    assert next_version("0.1.0", ["docs: actualizar README", "test: ampliar cobertura"]) is None


def test_latest_tag_returns_highest_semver(monkeypatch) -> None:
    monkeypatch.setattr(
        release_version,
        "git_output",
        lambda *args: "0.2.0\n0.10.0\n0.3.0\nnot-a-version",
    )

    assert release_version.latest_tag() == "0.10.0"
