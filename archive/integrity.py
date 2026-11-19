from hashlib import sha256


class BlockIntegrityError(OSError):
    """A block did not match its accepted bytes or fixed layout."""


def block_digest(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def verify_block(payload: bytes, expected: str, block_no: int) -> None:
    if block_digest(payload) != expected:
        raise BlockIntegrityError(f'checksum mismatch at block {block_no}')
