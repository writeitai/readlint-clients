"""The readlint.com Python SDK."""

from importlib.metadata import version

from readlint.client import Readlint, ReadlintError
from readlint.types import (
    Evaluation,
    EvaluationPage,
    EvaluationReport,
    EvaluationSummary,
)

__version__ = version("readlint")
__all__ = [
    "Evaluation",
    "EvaluationPage",
    "EvaluationReport",
    "EvaluationSummary",
    "Readlint",
    "ReadlintError",
]
