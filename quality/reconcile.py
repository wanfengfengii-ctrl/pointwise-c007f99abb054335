from collections.abc import Iterable
from dataclasses import dataclass

from quality.findings import BlockFinding, ordered_hits
from quality.thresholds import validate_threshold
from reader.observations import Observation


@dataclass(frozen=True)
class Reconciliation:
    threshold: int
    minimum: int
    maximum: int
    hits: tuple[BlockFinding, ...]

    @property
    def count(self) -> int:
        return len(self.hits)


def reconcile(
    observations: Iterable[Observation], block_count: int, threshold: int,
) -> Reconciliation:
    validate_threshold(threshold)
    ordered = tuple(observations)
    if block_count <= 0 or len(ordered) != block_count:
        raise ValueError('reconciliation requires every original block')
    if any(item.block_no != index for index, item in enumerate(ordered)):
        raise ValueError('observations do not cover the original block order')
    values = [item.value for item in ordered]
    return Reconciliation(threshold, min(values), max(values), ordered_hits(ordered, threshold))
