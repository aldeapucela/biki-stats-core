#!/usr/bin/env python3
"""Calcula la siguiente versión a partir de Conventional Commits."""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
COMMIT = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]*\))?(?P<breaking>!)?:\s")
RELEASE_TYPES = {"feat": "minor", "fix": "patch", "perf": "patch", "refactor": "patch"}


@dataclass(frozen=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> "Version":
        match = SEMVER.fullmatch(value)
        if not match:
            raise ValueError(f"Versión semántica inválida: {value}")
        return cls(*(int(part) for part in match.groups()))

    def bump(self, level: str) -> "Version":
        if level == "major":
            return Version(self.major + 1, 0, 0)
        if level == "minor":
            return Version(self.major, self.minor + 1, 0)
        return Version(self.major, self.minor, self.patch + 1)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def highest_bump(commits: list[str]) -> str | None:
    level = None
    rank = {"patch": 1, "minor": 2, "major": 3}
    for commit in commits:
        subject, _, body = commit.partition("\n")
        match = COMMIT.match(subject)
        if not match:
            continue
        candidate = (
            "major"
            if match.group("breaking") or "BREAKING CHANGE:" in body
            else RELEASE_TYPES.get(match.group("type"))
        )
        if candidate and (level is None or rank[candidate] > rank[level]):
            level = candidate
    return level


def next_version(base: str, commits: list[str]) -> str | None:
    bump = highest_bump(commits)
    return str(Version.parse(base).bump(bump)) if bump else None


def git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def latest_tag() -> str | None:
    tags = []
    for tag in git_output("tag", "--list").splitlines():
        if SEMVER.fullmatch(tag):
            tags.append(Version.parse(tag))
    return str(max(tags)) if tags else None


def commits_since(tag: str | None) -> list[str]:
    revision = f"{tag}..HEAD" if tag else "HEAD"
    output = git_output("log", "--format=%s%n%b%x00", revision)
    return [commit.strip() for commit in output.split("\x00") if commit.strip()]


def project_version() -> str:
    with Path("pyproject.toml").open("rb") as file:
        return tomllib.load(file)["project"]["version"]


def main() -> None:
    tag = latest_tag()
    base = tag or project_version()
    version = next_version(base, commits_since(tag))
    if version:
        print(version)


if __name__ == "__main__":
    main()
