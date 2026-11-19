import logging
from collections.abc import Callable

from archive.block_io import read_base_block, sync_base, write_base_block
from archive.catalog import get_reel
from archive.integrity import BlockIntegrityError, verify_block
from archive.workspace import Workspace, work_transaction
from reader.tasks import has_unreleased_tasks
from revision.journal import (
    correction_slots, get_active_change, get_change, published_checksum,
    record_cleanup_ready, record_finalization, record_placement, reels_awaiting_finalization,
)
from revision.media import correction_payload_size, read_correction_block, reclaim_correction_area


_LOG = logging.getLogger(__name__)


def finalize_if_ready(
    workspace: Workspace, reel_id: str, *, checkpoint: Callable[[str], None] | None = None,
) -> bool:
    with work_transaction(workspace) as database:
        change = get_active_change(database, reel_id)
        if change is None or change.state == 'pending':
            return False
        request_id = change.request_id
        if change.state == 'published':
            if has_unreleased_tasks(database, reel_id, change.parent_version):
                return False
            record_placement(database, request_id)

    verified = False
    with work_transaction(workspace) as database:
        change = get_change(database, request_id)
        if change.state == 'placing':
            reel = get_reel(database, reel_id)
            base_path = workspace.media / reel.base_name
            for entry in correction_slots(database, request_id).values():
                payload = read_correction_block(workspace, request_id, reel.layout, entry.slot)
                verify_block(payload, entry.digest, entry.block_no)
                write_base_block(base_path, reel.layout, entry.block_no, payload)
                sync_base(base_path)
                if entry.slot == 0 and checkpoint is not None:
                    checkpoint('first_base_synced')
            for block_no in range(reel.layout.block_count):
                payload = read_base_block(base_path, reel.layout, block_no)
                digest = published_checksum(database, reel, change.version, block_no)
                verify_block(payload, digest, block_no)
            record_cleanup_ready(database, request_id)
            verified = True

    if verified and checkpoint is not None:
        checkpoint('base_verified')
    with work_transaction(workspace) as database:
        change = get_change(database, request_id)
        if change.state == 'cleanup':
            reclaim_correction_area(workspace, request_id)
            if correction_payload_size(workspace, request_id) != 0:
                raise BlockIntegrityError('correction payload is still present after reclaim')
            if checkpoint is not None:
                checkpoint('correction_reclaimed')
            record_finalization(database, request_id)
    return True


def try_finalization(
    workspace: Workspace, reel_id: str, *, checkpoint: Callable[[str], None] | None = None,
) -> bool:
    try:
        return finalize_if_ready(workspace, reel_id, checkpoint=checkpoint)
    except OSError as error:
        _LOG.warning('Finalization still pending for reel %r: %s', reel_id, error)
        return False


def resume_finalization(workspace: Workspace) -> None:
    with work_transaction(workspace) as database:
        reels = reels_awaiting_finalization(database)
    for reel_id in reels:
        try_finalization(workspace, reel_id)
