from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

FindingStatus = Literal["EXPERIMENTAL", "BLOCKED", "NOT_APPLICABLE"]


@dataclass(frozen=True, slots=True)
class PdfContext:
    file_path: Path
    submission_root: Path
    node_id: str | None = None
    document_role: str | None = None
    language: str | None = None

    @property
    def relative_path(self) -> str:
        try:
            return self.file_path.resolve().relative_to(self.submission_root.resolve()).as_posix()
        except ValueError:
            return self.file_path.name


@dataclass(slots=True)
class Evidence:
    kind: str
    value: Any
    object_ref: str | None = None
    page: int | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Finding:
    rule_id: str
    title: str
    severity: str
    message: str
    evidence: list[Evidence] = field(default_factory=list)
    status: FindingStatus = "EXPERIMENTAL"
    confidence: Literal["high", "medium", "low"] = "high"
    applicability_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = [item.to_dict() for item in self.evidence]
        return payload


@dataclass(slots=True)
class ScanDiagnostics:
    pikepdf_open: str
    qpdf_check: str
    pdfium_open: str
    encrypted: bool | None
    password_required: bool
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScanResult:
    profile_id: str
    file: str
    context: dict[str, Any]
    diagnostics: ScanDiagnostics
    findings: list[Finding]
    observations: dict[str, Any]
    engine_status: str = "EXPERIMENTAL_CONTRACT_NOT_CDE_EQUIVALENCE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "file": self.file,
            "context": self.context,
            "diagnostics": self.diagnostics.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
            "observations": self.observations,
            "engine_status": self.engine_status,
        }
