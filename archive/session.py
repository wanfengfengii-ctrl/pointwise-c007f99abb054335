from pathlib import Path

from archive.importer import discard_unregistered_media
from archive.workspace import Workspace, open_workspace
from revision.finalize import resume_finalization


def open_archive(root: str | Path) -> Workspace:
    workspace = open_workspace(root)
    discard_unregistered_media(workspace)
    resume_finalization(workspace)
    return workspace
