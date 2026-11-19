import json
import sqlite3
from dataclasses import dataclass

from archive.layout import BlockLayout


@dataclass(frozen=True)
class ReelRecord:
    reel_id: str
    layout: BlockLayout
    base_name: str
    original_checks: tuple[str, ...]
    initial_version: int = 1


def validate_reel_id(reel_id: str) -> None:
    if type(reel_id) is not str or not reel_id.strip():
        raise ValueError('reel number must be nonempty text')
    reel_id.encode('utf-8')


def register_reel(database: sqlite3.Connection, reel: ReelRecord) -> None:
    database.execute(
        'INSERT INTO reels(reel_id, block_count, block_width, base_name, original_checks) '
        'VALUES (?, ?, ?, ?, ?)',
        (reel.reel_id, reel.layout.block_count, reel.layout.block_width,
         reel.base_name, json.dumps(reel.original_checks, separators=(',', ':'))),
    )


def get_reel(database: sqlite3.Connection, reel_id: str) -> ReelRecord:
    validate_reel_id(reel_id)
    row = database.execute('SELECT * FROM reels WHERE reel_id = ?', (reel_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown reel {reel_id!r}')
    return ReelRecord(
        row['reel_id'], BlockLayout(row['block_count'], row['block_width']), row['base_name'],
        tuple(json.loads(row['original_checks'])),
    )
