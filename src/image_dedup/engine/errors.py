"""Scan error collection — tracks failures for post-scan reporting."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScanErrorRecord:
    file_path: str
    stage: str        # "scan", "hash", "feature"
    error_type: str
    message: str


@dataclass
class ScanErrors:
    records: list[ScanErrorRecord] = field(default_factory=list)

    def add(self, file_path: str, stage: str, exc: Exception) -> None:
        self.records.append(ScanErrorRecord(
            file_path=file_path,
            stage=stage,
            error_type=type(exc).__name__,
            message=str(exc),
        ))

    @property
    def count(self) -> int:
        return len(self.records)
