from dataclasses import dataclass


@dataclass(frozen=True)
class BlockLayout:
    block_count: int
    block_width: int


def validate_layout(layout: BlockLayout) -> BlockLayout:
    if not isinstance(layout, BlockLayout):
        raise ValueError('expected a block layout')
    if type(layout.block_count) is not int or layout.block_count <= 0:
        raise ValueError('block count must be a positive integer')
    if type(layout.block_width) is not int or layout.block_width <= 0:
        raise ValueError('block width must be a positive integer')
    if layout.block_count * layout.block_width > 2**63 - 1:
        raise ValueError('layout exceeds the file offset range')
    return layout


def block_offset(layout: BlockLayout, block_no: int) -> int:
    if type(block_no) is not int or not 0 <= block_no < layout.block_count:
        raise ValueError(f'invalid original block number {block_no!r}')
    return block_no * layout.block_width


def block_length(layout: BlockLayout, block_no: int) -> int:
    block_offset(layout, block_no)
    return layout.block_width
