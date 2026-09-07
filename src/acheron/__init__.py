"""ACHERON public scripting API."""
from .model import AnalysisError, Limits
from .project import Project, analyze, open_project as open

__version__ = "0.4.0"
__all__ = ["AnalysisError", "Limits", "Project", "analyze", "open"]
