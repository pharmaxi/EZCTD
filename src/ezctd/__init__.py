"""EZCTD experimental read-only PDF observation package."""

__version__ = "0.4.0.dev0"

from .catalog import RuleCatalog, RuleMetadata
from .models import Evidence, Finding, PdfContext, ScanDiagnostics, ScanResult

__all__ = [
    "Evidence",
    "ExperimentalPdfObserver",
    "Finding",
    "PdfContext",
    "RuleCatalog",
    "RuleMetadata",
    "ScanDiagnostics",
    "ScanResult",
]


def __getattr__(name: str):
    # Importers and the parent process do not load native PDF engines.
    if name == "ExperimentalPdfObserver":
        from .pdf_observer import ExperimentalPdfObserver
        return ExperimentalPdfObserver
    raise AttributeError(name)
