import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    block_no: int
    value: int


def record_observations(
    database: sqlite3.Connection, task_id: int, observations: Iterable[Observation],
) -> None:
    # Text encoding preserves signed integers from any supported physical block width.
    database.executemany(
        'INSERT INTO observations(task_id, block_no, reading) VALUES (?, ?, ?)',
        ((task_id, item.block_no, format(item.value, 'x')) for item in observations),
    )


def iter_observations(database: sqlite3.Connection, task_id: int) -> Iterator[Observation]:
    rows = database.execute(
        'SELECT block_no, reading FROM observations WHERE task_id = ? ORDER BY block_no', (task_id,),
    )
    for row in rows:
        yield Observation(row['block_no'], int(row['reading'], 16))
