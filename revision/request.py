import json
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256

from archive.catalog import ReelRecord
from archive.integrity import block_digest
from quality.correction_rules import validate_replacements


@dataclass(frozen=True)
class AmendRequest:
    request_id: str
    reel_id: str
    parent_version: int
    replacements: tuple[tuple[int, bytes], ...]
    checks: tuple[tuple[int, str], ...]


def normalize_request(
    reel: ReelRecord, request_id: str, parent_version: int,
    replacements: Iterable[tuple[int, bytes]],
) -> AmendRequest:
    if type(request_id) is not str or not request_id.strip():
        raise ValueError('request number must be nonempty text')
    request_id.encode('utf-8')
    if type(parent_version) is not int or not 0 < parent_version <= 2**63 - 1:
        raise ValueError('invalid parent version')
    ordered = validate_replacements(reel.layout, replacements)
    checks = tuple((block_no, block_digest(payload)) for block_no, payload in ordered)
    return AmendRequest(request_id, reel.reel_id, parent_version, ordered, checks)


def request_identity(request: AmendRequest) -> str:
    body = [request.request_id, request.reel_id, request.parent_version, request.checks]
    return sha256(json.dumps(body, separators=(',', ':')).encode('utf-8')).hexdigest()
