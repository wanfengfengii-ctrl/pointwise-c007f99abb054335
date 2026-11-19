import sqlite3

from archive.block_io import read_base_block
from archive.catalog import ReelRecord
from archive.integrity import verify_block
from archive.workspace import Workspace
from reader.tasks import ReadTask
from revision.journal import ChangeRecord, CorrectionSlot, published_checksum
from revision.media import read_correction_block


def decode_reading(payload: bytes) -> int:
    return int.from_bytes(payload, byteorder='little', signed=True)


def read_task_block(
    database: sqlite3.Connection, workspace: Workspace, reel: ReelRecord, task: ReadTask,
    block_no: int, active: ChangeRecord | None, slots: dict[int, CorrectionSlot],
) -> int:
    entry = slots.get(block_no)
    if (entry is not None and active is not None and task.version == active.version
            and active.state in ('published', 'placing')):
        payload = read_correction_block(workspace, active.request_id, reel.layout, entry.slot)
    else:
        payload = read_base_block(workspace.media / reel.base_name, reel.layout, block_no)
    digest = published_checksum(database, reel, task.version, block_no)
    verify_block(payload, digest, block_no)
    return decode_reading(payload)
