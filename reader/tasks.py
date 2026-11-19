import sqlite3
from dataclasses import dataclass

from archive.catalog import get_reel
from archive.workspace import Workspace, work_transaction
from revision.journal import current_revision


@dataclass(frozen=True)
class ReadTask:
    task_id: int
    reel_id: str
    version: int
    source_request: str | None
    cursor: int
    released: bool


def open(workspace: Workspace, reel_id: str) -> ReadTask:
    with work_transaction(workspace) as database:
        reel = get_reel(database, reel_id)
        version, source = current_revision(database, reel)
        row = database.execute(
            'INSERT INTO tasks(reel_id, version, source_request) VALUES (?, ?, ?)',
            (reel_id, version, source),
        )
        return ReadTask(row.lastrowid, reel_id, version, source, 0, False)


def get_task(database: sqlite3.Connection, task_id: int) -> ReadTask:
    if type(task_id) is not int or not 0 < task_id <= 2**63 - 1:
        raise ValueError('invalid task number')
    row = database.execute('SELECT * FROM tasks WHERE task_id = ?', (task_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown task {task_id}')
    return ReadTask(row['task_id'], row['reel_id'], row['version'], row['source_request'],
                    row['cursor'], bool(row['released']))


def has_unreleased_tasks(database: sqlite3.Connection, reel_id: str, version: int) -> bool:
    return database.execute(
        'SELECT 1 FROM tasks WHERE reel_id = ? AND version = ? AND released = 0 LIMIT 1',
        (reel_id, version),
    ).fetchone() is not None
