"""Provider-neutral Git domain primitives."""

from .policy import ProtectedBranchError, ProtectedBranchPolicy

__all__ = ["ProtectedBranchError", "ProtectedBranchPolicy"]
