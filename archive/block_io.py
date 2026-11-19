import os
from pathlib import Path

from archive.integrity import BlockIntegrityError
from archive.layout import BlockLayout, block_length, block_offset


def read_base_block(path: Path, layout: BlockLayout, block_no: int) -> bytes:
    offset = block_offset(layout, block_no)
    width = block_length(layout, block_no)
    with path.open('rb', buffering=0) as stream:
        stream.seek(offset)
        payload = stream.read(width)
    if len(payload) != width:
        raise BlockIntegrityError(f'short base read at block {block_no}')
    return payload


def write_base_block(path: Path, layout: BlockLayout, block_no: int, payload: bytes) -> None:
    offset = block_offset(layout, block_no)
    width = block_length(layout, block_no)
    if len(payload) != width:
        raise ValueError(f'wrong base write length at block {block_no}')
    with path.open('r+b', buffering=0) as stream:
        stream.seek(offset)
        if stream.write(payload) != width:
            raise OSError(f'short base write at block {block_no}')


def sync_base(path: Path) -> None:
    with path.open('r+b', buffering=0) as stream:
        os.fsync(stream.fileno())


def sync_directory(path: Path) -> None:
    if os.name == 'posix':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
