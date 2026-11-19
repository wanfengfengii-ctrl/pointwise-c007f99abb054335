from collections.abc import Callable, Iterable
from dataclasses import dataclass

from archive.catalog import get_reel
from archive.integrity import BlockIntegrityError, verify_block
from archive.workspace import Workspace, work_transaction
from revision.finalize import try_finalization
from revision.journal import (
    correction_slots, current_revision, get_active_change, get_change, record_pending,
    record_publication,
)
from revision.media import (
    correction_payload_size, read_correction_block, sync_correction_area, write_correction_block,
)
from revision.request import normalize_request, request_identity


@dataclass(frozen=True)
class AmendReceipt:
    reel_id: str
    request_id: str
    version: int


def amend(
    workspace: Workspace, reel_id: str, request_id: str, parent_version: int,
    replacements: Iterable[tuple[int, bytes]], *, checkpoint: Callable[[str], None] | None = None,
) -> AmendReceipt:
    with work_transaction(workspace) as database:
        reel = get_reel(database, reel_id)
        request = normalize_request(reel, request_id, parent_version, replacements)
        identity = request_identity(request)
        existing = get_change(database, request_id)
        if existing is not None:
            if existing.identity != identity:
                raise ValueError(f'request number already bound to different inputs: {request_id!r}')
            if existing.state != 'pending':
                return AmendReceipt(existing.reel_id, existing.request_id, existing.version)
        else:
            current, _ = current_revision(database, reel)
            if parent_version != current:
                raise ValueError(f'expected parent version {current}, got {parent_version}')
            if get_active_change(database, reel_id) is not None:
                raise ValueError(f'an unfinalized correction exists for reel {reel_id!r}')
            if current == 2**63 - 1:
                raise ValueError('reel has exhausted its version numbers')
            record_pending(database, request, identity)

    with work_transaction(workspace) as database:
        change = get_change(database, request_id)
        receipt = AmendReceipt(change.reel_id, change.request_id, change.version)
        if change.state != 'pending':
            return receipt
        slots = correction_slots(database, request_id)
        for block_no, payload in request.replacements:
            entry = slots[block_no]
            write_correction_block(workspace, request_id, reel.layout, entry.slot, payload)
            sync_correction_area(workspace, request_id)
            if entry.slot == 0 and checkpoint is not None:
                checkpoint('first_payload_synced')
        if correction_payload_size(workspace, request_id) != len(slots) * reel.layout.block_width:
            raise BlockIntegrityError('wrong correction area size before publication')
        for entry in slots.values():
            payload = read_correction_block(workspace, request_id, reel.layout, entry.slot)
            verify_block(payload, entry.digest, entry.block_no)
        record_publication(database, request_id)

    if checkpoint is not None:
        checkpoint('publication_committed')
    try_finalization(workspace, reel_id, checkpoint=checkpoint)
    return receipt
