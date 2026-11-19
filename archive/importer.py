import re
from collections.abc import Iterable
from hashlib import sha256

from archive.block_io import sync_base, sync_directory, write_base_block
from archive.catalog import ReelRecord, register_reel, validate_reel_id
from archive.integrity import verify_block
from archive.layout import BlockLayout, block_length, validate_layout
from archive.workspace import Workspace, work_transaction


_BASE_NAME = re.compile(r'base-[0-9a-f]{64}\.bin')


def ingest(
    workspace: Workspace,
    reel_id: str,
    layout: BlockLayout,
    blocks: Iterable[bytes],
    checksums: Iterable[str],
) -> ReelRecord:
    validate_reel_id(reel_id)
    validate_layout(layout)
    payloads = tuple(blocks)
    checks = tuple(checksums)
    if len(payloads) != layout.block_count or len(checks) != layout.block_count:
        raise ValueError('layout, payload count and checksum count must agree')
    for block_no, (payload, expected) in enumerate(zip(payloads, checks, strict=True)):
        if type(payload) is not bytes or len(payload) != block_length(layout, block_no):
            raise ValueError(f'invalid payload at block {block_no}')
        verify_block(payload, expected, block_no)

    base_name = 'base-' + sha256(reel_id.encode('utf-8')).hexdigest() + '.bin'
    reel = ReelRecord(reel_id, layout, base_name, checks)
    with work_transaction(workspace) as database:
        if database.execute('SELECT 1 FROM reels WHERE reel_id = ?', (reel_id,)).fetchone():
            raise ValueError(f'reel number already registered: {reel_id!r}')
        path = workspace.media / base_name
        # A previous uncommitted import of this reel can have left an orphan.
        with path.open('wb'):
            pass
        for block_no, payload in enumerate(payloads):
            write_base_block(path, layout, block_no, payload)
        sync_base(path)
        sync_directory(workspace.media)
        register_reel(database, reel)
    return reel


def discard_unregistered_media(workspace: Workspace) -> None:
    with work_transaction(workspace) as database:
        registered = {row['base_name'] for row in database.execute('SELECT base_name FROM reels')}
        removed = False
        for path in workspace.media.iterdir():
            if _BASE_NAME.fullmatch(path.name) and path.name not in registered:
                path.unlink()
                removed = True
        if removed:
            sync_directory(workspace.media)
