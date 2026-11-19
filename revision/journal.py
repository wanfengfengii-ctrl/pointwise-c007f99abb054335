import sqlite3
from dataclasses import dataclass

from archive.catalog import ReelRecord
from revision.request import AmendRequest


@dataclass(frozen=True)
class ChangeRecord:
    request_id: str
    reel_id: str
    parent_version: int
    version: int
    identity: str
    state: str


@dataclass(frozen=True)
class CorrectionSlot:
    block_no: int
    slot: int
    digest: str


def get_change(database: sqlite3.Connection, request_id: str) -> ChangeRecord | None:
    row = database.execute('SELECT * FROM changes WHERE request_id = ?', (request_id,)).fetchone()
    return None if row is None else ChangeRecord(**dict(row))


def get_active_change(database: sqlite3.Connection, reel_id: str) -> ChangeRecord | None:
    row = database.execute(
        "SELECT * FROM changes WHERE reel_id = ? AND state <> 'finalized'", (reel_id,),
    ).fetchone()
    return None if row is None else ChangeRecord(**dict(row))


def current_revision(database: sqlite3.Connection, reel: ReelRecord) -> tuple[int, str | None]:
    row = database.execute(
        "SELECT version, request_id FROM changes WHERE reel_id = ? AND state <> 'pending' "
        'ORDER BY version DESC LIMIT 1', (reel.reel_id,),
    ).fetchone()
    if row is None:
        return reel.initial_version, None
    return row['version'], row['request_id']


def record_pending(database: sqlite3.Connection, request: AmendRequest, identity: str) -> None:
    database.execute(
        'INSERT INTO changes(request_id, reel_id, parent_version, version, identity, state) '
        "VALUES (?, ?, ?, ?, ?, 'pending')",
        (request.request_id, request.reel_id, request.parent_version,
         request.parent_version + 1, identity),
    )
    database.executemany(
        'INSERT INTO change_blocks(request_id, block_no, slot, digest) VALUES (?, ?, ?, ?)',
        ((request.request_id, block_no, slot, digest)
         for slot, (block_no, digest) in enumerate(request.checks)),
    )


def correction_slots(database: sqlite3.Connection, request_id: str) -> dict[int, CorrectionSlot]:
    rows = database.execute(
        'SELECT block_no, slot, digest FROM change_blocks WHERE request_id = ? ORDER BY slot',
        (request_id,),
    )
    return {row['block_no']: CorrectionSlot(**dict(row)) for row in rows}


def published_checksum(
    database: sqlite3.Connection, reel: ReelRecord, version: int, block_no: int,
) -> str:
    row = database.execute(
        'SELECT b.digest FROM changes c JOIN change_blocks b USING (request_id) '
        "WHERE c.reel_id = ? AND c.version <= ? AND c.state <> 'pending' AND b.block_no = ? "
        'ORDER BY c.version DESC LIMIT 1', (reel.reel_id, version, block_no),
    ).fetchone()
    return reel.original_checks[block_no] if row is None else row['digest']


def _transition(database: sqlite3.Connection, request_id: str, previous: str, state: str) -> None:
    result = database.execute(
        'UPDATE changes SET state = ? WHERE request_id = ? AND state = ?',
        (state, request_id, previous),
    )
    if result.rowcount != 1:
        raise RuntimeError(f'cannot move request {request_id!r} from {previous} to {state}')


def record_publication(database: sqlite3.Connection, request_id: str) -> None:
    _transition(database, request_id, 'pending', 'published')


def record_placement(database: sqlite3.Connection, request_id: str) -> None:
    _transition(database, request_id, 'published', 'placing')


def record_cleanup_ready(database: sqlite3.Connection, request_id: str) -> None:
    _transition(database, request_id, 'placing', 'cleanup')


def record_finalization(database: sqlite3.Connection, request_id: str) -> None:
    _transition(database, request_id, 'cleanup', 'finalized')


def reels_awaiting_finalization(database: sqlite3.Connection) -> tuple[str, ...]:
    rows = database.execute(
        "SELECT reel_id FROM changes WHERE state IN ('published', 'placing', 'cleanup') ORDER BY reel_id",
    )
    return tuple(row['reel_id'] for row in rows)
