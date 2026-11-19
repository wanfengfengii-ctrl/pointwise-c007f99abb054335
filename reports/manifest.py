import json
from dataclasses import dataclass

from quality.findings import BlockFinding
from quality.reconcile import Reconciliation
from reader.tasks import ReadTask


@dataclass(frozen=True)
class ReportManifest:
    report_id: int
    task_id: int
    reel_id: str
    version: int
    source_request: str | None
    threshold: int
    minimum: int
    maximum: int
    hits: tuple[BlockFinding, ...]
    count: int


def build_manifest(report_id: int, task: ReadTask, totals: Reconciliation) -> ReportManifest:
    return ReportManifest(report_id, task.task_id, task.reel_id, task.version, task.source_request,
                          totals.threshold, totals.minimum, totals.maximum, totals.hits, totals.count)


def encode_manifest(manifest: ReportManifest) -> str:
    # Keep arbitrary-width integer readings independent of SQLite and JSON decimal limits.
    payload = {
        'report_id': manifest.report_id,
        'task_id': manifest.task_id,
        'reel_id': manifest.reel_id,
        'version': manifest.version,
        'source_request': manifest.source_request,
        'threshold': format(manifest.threshold, 'x'),
        'minimum': format(manifest.minimum, 'x'),
        'maximum': format(manifest.maximum, 'x'),
        'hits': [[hit.block_no, format(hit.value, 'x')] for hit in manifest.hits],
        'count': manifest.count,
    }
    return json.dumps(payload, sort_keys=True, separators=(',', ':'))


def decode_manifest(payload: str) -> ReportManifest:
    fields = json.loads(payload)
    for field in ('threshold', 'minimum', 'maximum'):
        fields[field] = int(fields[field], 16)
    fields['hits'] = tuple(BlockFinding(block_no, int(value, 16)) for block_no, value in fields['hits'])
    if fields['count'] != len(fields['hits']):
        raise ValueError('sealed report count does not match its findings')
    return ReportManifest(**fields)
