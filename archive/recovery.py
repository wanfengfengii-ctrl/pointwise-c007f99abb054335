import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from archive.layout import BlockLayout, block_offset


@dataclass(frozen=True)
class RecoveredBlock:
    block_no: int
    original_hex: str
    group_ids: tuple[str, ...]


def validate_groups(
    layout: BlockLayout, groups: Iterable[tuple[str, Iterable[int], bytes]],
) -> tuple[tuple[str, tuple[int, ...], bytes], ...]:
    normalized = []
    seen = set()
    for entry in groups:
        try:
            group_id, block_numbers, parity = entry
        except (TypeError, ValueError):
            raise ValueError('each group must be a (group id, block numbers, parity) triple') from None
        if type(group_id) is not str or not group_id.strip():
            raise ValueError('group id must be nonempty text')
        group_id.encode('utf-8')
        if group_id in seen:
            raise ValueError(f'duplicate group id: {group_id!r}')
        seen.add(group_id)
        try:
            numbers = tuple(block_numbers)
        except TypeError:
            raise ValueError(f'group {group_id!r} block numbers must be an iterable') from None
        if not numbers:
            raise ValueError(f'group {group_id!r} must list at least one block')
        for block_no in numbers:
            block_offset(layout, block_no)
        if len(set(numbers)) != len(numbers):
            raise ValueError(f'duplicate block number in group {group_id!r}')
        if type(parity) is not bytes or len(parity) != layout.block_width:
            raise ValueError(f'group {group_id!r} parity must be {layout.block_width} bytes')
        normalized.append((group_id, numbers, parity))
    return tuple(normalized)


def solve_missing(
    payloads: tuple[bytes | None, ...],
    groups: tuple[tuple[str, tuple[int, ...], bytes], ...],
) -> dict[int, tuple[bytes, tuple[str, ...]]]:
    """Determine every missing block from the parity groups alone.

    Returns each missing block number mapped to its recovered bytes and a
    witness: the sorted group ids whose equations combine to that block.
    Raises ValueError when the groups contradict each other or leave any
    missing block undetermined.
    """
    missing = sum(payload is None for payload in payloads)
    pivots: dict[int, list] = {}

    def combine(target: list, source: list) -> None:
        target[0].symmetric_difference_update(source[0])
        for index, byte in enumerate(source[1]):
            target[1][index] ^= byte
        target[2].symmetric_difference_update(source[2])

    for group_id, numbers, parity in groups:
        variables = set()
        constant = bytearray(parity)
        for block_no in numbers:
            arrived = payloads[block_no]
            if arrived is None:
                variables.add(block_no)
            else:
                for index, byte in enumerate(arrived):
                    constant[index] ^= byte
        equation = [variables, constant, {group_id}]
        while True:
            shared = equation[0].intersection(pivots)
            if not shared:
                break
            combine(equation, pivots[min(shared)])
        if not equation[0]:
            if any(equation[1]):
                raise ValueError(f'contradictory parity group {group_id!r}')
            continue
        pivot = min(equation[0])
        for other in pivots.values():
            if pivot in other[0]:
                combine(other, equation)
        pivots[pivot] = equation
    if len(pivots) != missing:
        raise ValueError('parity groups do not determine every missing block')
    # With every missing block pivoted, each pivot equation names only its own
    # block, so its constant is the recovered payload and its groups a witness.
    return {block_no: (bytes(equation[1]), tuple(sorted(equation[2])))
            for block_no, equation in pivots.items()}


def register_recovery(
    database: sqlite3.Connection, reel_id: str, recovered: Iterable[RecoveredBlock],
) -> None:
    database.executemany(
        'INSERT INTO recovered_blocks(reel_id, block_no, original_hex, group_ids) '
        'VALUES (?, ?, ?, ?)',
        ((reel_id, item.block_no, item.original_hex,
          json.dumps(list(item.group_ids), separators=(',', ':')))
         for item in recovered),
    )


def recovered_blocks(database: sqlite3.Connection, reel_id: str) -> tuple[RecoveredBlock, ...] | None:
    rows = database.execute(
        'SELECT block_no, original_hex, group_ids FROM recovered_blocks '
        'WHERE reel_id = ? ORDER BY block_no', (reel_id,),
    ).fetchall()
    if not rows:
        return None
    return tuple(
        RecoveredBlock(row['block_no'], row['original_hex'], tuple(json.loads(row['group_ids'])))
        for row in rows
    )
