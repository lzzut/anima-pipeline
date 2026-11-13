"""Repository paths shared by all entry points, independent of the current directory."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
WORKFLOW_DIR = PROJECT_ROOT / "workflows"
