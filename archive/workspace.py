import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from archive.block_io import sync_directory


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def media(self) -> Path:
        return self.root / 'media'

    @property
    def database(self) -> Path:
        return self.root / 'catalog.sqlite3'


_SCHEMA = '''
CREATE TABLE IF NOT EXISTS reels (
    reel_id TEXT PRIMARY KEY NOT NULL,
    block_count INTEGER NOT NULL CHECK (block_count > 0),
    block_width INTEGER NOT NULL CHECK (block_width > 0),
    base_name TEXT NOT NULL UNIQUE,
    original_checks TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS changes (
    request_id TEXT PRIMARY KEY NOT NULL,
    reel_id TEXT NOT NULL REFERENCES reels(reel_id),
    parent_version INTEGER NOT NULL,
    version INTEGER NOT NULL CHECK (version = parent_version + 1),
    identity TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'published', 'placing', 'cleanup', 'finalized')),
    UNIQUE (reel_id, version)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_change
    ON changes(reel_id) WHERE state <> 'finalized';
CREATE TABLE IF NOT EXISTS change_blocks (
    request_id TEXT NOT NULL REFERENCES changes(request_id),
    block_no INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    digest TEXT NOT NULL,
    PRIMARY KEY (request_id, block_no),
    UNIQUE (request_id, slot)
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id INTEGER PRIMARY KEY,
    reel_id TEXT NOT NULL REFERENCES reels(reel_id),
    version INTEGER NOT NULL,
    source_request TEXT REFERENCES changes(request_id),
    cursor INTEGER NOT NULL DEFAULT 0 CHECK (cursor >= 0),
    released INTEGER NOT NULL DEFAULT 0 CHECK (released IN (0, 1))
);
CREATE INDEX IF NOT EXISTS active_task_versions
    ON tasks(reel_id, version) WHERE released = 0;
CREATE TABLE IF NOT EXISTS observations (
    task_id INTEGER NOT NULL REFERENCES tasks(task_id),
    block_no INTEGER NOT NULL,
    reading TEXT NOT NULL,
    PRIMARY KEY (task_id, block_no)
);
CREATE TABLE IF NOT EXISTS reports (
    report_id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES tasks(task_id),
    manifest TEXT NOT NULL
);
'''


@contextmanager
def work_transaction(workspace: Workspace):
    """Serialize catalogue decisions together with the associated media access."""
    database = sqlite3.connect(workspace.database, timeout=30, isolation_level=None)
    try:
        database.row_factory = sqlite3.Row
        database.execute('PRAGMA foreign_keys = ON')
        database.execute('PRAGMA synchronous = FULL')
        database.execute('BEGIN IMMEDIATE')
        yield database
        database.commit()
    except BaseException:
        if database.in_transaction:
            database.rollback()
        raise
    finally:
        database.close()


def initialize_workspace(workspace: Workspace) -> None:
    workspace.media.mkdir(parents=True, exist_ok=True)
    with work_transaction(workspace) as database:
        for statement in _SCHEMA.split(';'):
            if statement.strip():
                database.execute(statement)
    sync_directory(workspace.root)


def open_workspace(root: str | Path) -> Workspace:
    workspace = Workspace(Path(root).resolve())
    initialize_workspace(workspace)
    return workspace
