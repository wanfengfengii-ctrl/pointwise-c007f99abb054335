from collections.abc import Iterable

from archive.layout import BlockLayout, block_length


def validate_replacements(
    layout: BlockLayout, replacements: Iterable[tuple[int, bytes]],
) -> tuple[tuple[int, bytes], ...]:
    accepted = {}
    for block_no, payload in replacements:
        width = block_length(layout, block_no)
        if block_no in accepted:
            raise ValueError(f'duplicate replacement block {block_no}')
        if type(payload) is not bytes or len(payload) != width:
            raise ValueError(f'replacement block {block_no} must contain {width} bytes')
        accepted[block_no] = payload
    if not accepted:
        raise ValueError('empty correction request')
    return tuple(sorted(accepted.items()))
