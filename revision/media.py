import os
from hashlib import sha256
from pathlib import Path

from archive.block_io import sync_directory
from archive.integrity import BlockIntegrityError
from archive.layout import BlockLayout, block_offset
from archive.workspace import Workspace


def _area_path(workspace: Workspace, request_id: str) -> Path:
    digest = sha256(request_id.encode('utf-8')).hexdigest()
    return workspace.media / f'fix-{digest}.bin'


def write_correction_block(
    workspace: Workspace, request_id: str, layout: BlockLayout, slot: int, payload: bytes,
) -> None:
    offset = block_offset(layout, slot)
    if len(payload) != layout.block_width:
        raise ValueError(f'wrong correction payload length for slot {slot}')
    descriptor = os.open(_area_path(workspace, request_id), os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, 'r+b', buffering=0) as stream:
        if offset > os.fstat(stream.fileno()).st_size:
            raise OSError(f'correction slot {slot} would leave a hole')
        stream.seek(offset)
        if stream.write(payload) != layout.block_width:
            raise OSError(f'short correction write in slot {slot}')


def read_correction_block(
    workspace: Workspace, request_id: str, layout: BlockLayout, slot: int,
) -> bytes:
    offset = block_offset(layout, slot)
    with _area_path(workspace, request_id).open('rb', buffering=0) as stream:
        stream.seek(offset)
        payload = stream.read(layout.block_width)
    if len(payload) != layout.block_width:
        raise BlockIntegrityError(f'short correction read in slot {slot}')
    return payload


def sync_correction_area(workspace: Workspace, request_id: str) -> None:
    with _area_path(workspace, request_id).open('r+b', buffering=0) as stream:
        os.fsync(stream.fileno())
    sync_directory(workspace.media)


def correction_payload_size(workspace: Workspace, request_id: str) -> int:
    """Count actual file bytes, including any unfinished payload on disk."""
    try:
        return _area_path(workspace, request_id).stat().st_size
    except FileNotFoundError:
        return 0


def reclaim_correction_area(workspace: Workspace, request_id: str) -> None:
    _area_path(workspace, request_id).unlink(missing_ok=True)
    sync_directory(workspace.media)
