"""Fuente HTTP para snapshots de históricos almacenados en GitHub."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class HistoryFile:
    path: str
    blob_sha: str
    size: int


@dataclass(frozen=True, slots=True)
class HistorySnapshot:
    repository: str
    requested_ref: str
    commit: str
    files: tuple[HistoryFile, ...]
    manifest_json: str


class GitHubHistorySource:
    """Descubre y descarga los CSV de un commit concreto sin usar Git."""

    def __init__(
        self,
        repository: str,
        ref: str = "main",
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.repository = repository
        self.ref = ref
        self.timeout = timeout
        self._client = client

    def snapshot(self) -> HistorySnapshot:
        owns_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            commit_response = client.get(
                f"https://api.github.com/repos/{self.repository}/commits/{self.ref}"
            )
            commit_response.raise_for_status()
            commit = str(commit_response.json()["sha"])

            tree_response = client.get(
                f"https://api.github.com/repos/{self.repository}/git/trees/{commit}",
                params={"recursive": "1"},
            )
            tree_response.raise_for_status()
            tree = tree_response.json()
            if tree.get("truncated"):
                raise RuntimeError("El árbol de GitHub está truncado; no se puede inventariar")
            files = tuple(
                HistoryFile(
                    path=item["path"],
                    blob_sha=item["sha"],
                    size=int(item.get("size", 0)),
                )
                for item in tree.get("tree", [])
                if item.get("type") == "blob"
                and item.get("path", "").startswith("data/")
                and item.get("path", "").lower().endswith(".csv")
            )
            if not files:
                raise RuntimeError("El snapshot no contiene CSV bajo data/")
            manifest = [
                {"path": item.path, "blob_sha": item.blob_sha, "size": item.size}
                for item in sorted(files, key=lambda item: item.path)
            ]
            manifest_json = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"))
            return HistorySnapshot(
                repository=self.repository,
                requested_ref=self.ref,
                commit=commit,
                files=tuple(sorted(files, key=lambda item: item.path)),
                manifest_json=manifest_json,
            )
        finally:
            if owns_client:
                client.close()

    def stream_csv(self, snapshot: HistorySnapshot, file: HistoryFile) -> Iterator[str]:
        client = self._client or httpx.Client(timeout=self.timeout)
        response = client.stream(
            "GET",
            f"https://raw.githubusercontent.com/{snapshot.repository}/{snapshot.commit}/{file.path}",
        )
        try:
            with response as streamed:
                streamed.raise_for_status()
                for line in streamed.iter_lines():
                    yield f"{line}\n"
        finally:
            if self._client is None:
                client.close()
