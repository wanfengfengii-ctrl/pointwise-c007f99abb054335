from collections.abc import Iterable
from dataclasses import dataclass

from quality.thresholds import meets_threshold
from reader.observations import Observation


@dataclass(frozen=True)
class BlockFinding:
    block_no: int
    value: int


def ordered_hits(observations: Iterable[Observation], threshold: int) -> tuple[BlockFinding, ...]:
    return tuple(BlockFinding(item.block_no, item.value) for item in observations
                 if meets_threshold(item.value, threshold))
