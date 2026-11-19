import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.importer import ingest
from archive.layout import BlockLayout
from archive.session import open_archive
from reader.cursor import next as read_next
from reader.release import finish
from reader.tasks import open as open_task
from reports.issue import report
from revision.media import correction_payload_size
from revision.publication import amend


EXAMPLES = Path(__file__).resolve().parent / 'examples'


def load_reel(path: Path):
    data = json.loads(path.read_text(encoding='utf-8'))
    layout = BlockLayout(data['block_count'], data['block_width'])
    return (data['reel_id'], layout, [bytes.fromhex(block) for block in data['blocks_hex']],
            data['checksums'])


def load_correction(path: Path):
    data = json.loads(path.read_text(encoding='utf-8'))
    replacements = [(block_no, bytes.fromhex(payload)) for block_no, payload in data['replacements']]
    return data['reel_id'], data['request_id'], data['parent_version'], replacements


def main() -> None:
    with TemporaryDirectory(prefix='scan-reel-demo-') as directory:
        workspace = open_archive(directory)
        reel = ingest(workspace, *load_reel(EXAMPLES / 'reel.json'))
        white = open_task(workspace, reel.reel_id)
        white_prefix = read_next(workspace, white.task_id, 2)
        receipt = amend(workspace, *load_correction(EXAMPLES / 'correction.json'))
        payload_before = correction_payload_size(workspace, receipt.request_id)
        workspace = open_archive(directory)
        night = open_task(workspace, reel.reel_id)
        night_values = read_next(workspace, night.task_id, 4)
        white_tail = read_next(workspace, white.task_id, 4)
        white_report = report(workspace, task_id=white.task_id, threshold=26)
        night_report = report(workspace, task_id=night.task_id, threshold=26)
        finish(workspace, white.task_id)
        finish(workspace, night.task_id)
        workspace = open_archive(directory)
        history = [report(workspace, report_id=result['report_id'])
                   for result in (white_report, night_report)]
        actual = {
            'versions': [white.version, night.version],
            'readings': [[item.value for item in white_prefix + white_tail],
                         [item.value for item in night_values]],
            'correction_bytes': [payload_before, correction_payload_size(workspace, receipt.request_id)],
        }
        expected = {'versions': [1, 2], 'readings': [[12, 18, 25, 31], [12, 18, 26, 33]],
                    'correction_bytes': [8, 0]}
        summaries = [{key: result[key] for key in ('version', 'source_request', 'range', 'hits', 'count')}
                     for result in history]
        expected_summaries = [
            {'version': 1, 'source_request': None, 'range': [12, 31],
             'hits': [{'block_no': 3, 'value': 31}], 'count': 1},
            {'version': 2, 'source_request': 'replace-tail', 'range': [12, 33],
             'hits': [{'block_no': 2, 'value': 26}, {'block_no': 3, 'value': 33}], 'count': 2},
        ]
        if actual != expected or summaries != expected_summaries or history != [white_report, night_report]:
            raise RuntimeError('shift readings or sealed reconciliation did not match the sample ledger')
        print(json.dumps({'receipt': asdict(receipt), 'reports': history}, ensure_ascii=False, sort_keys=True))
        evidence = {
            'case_id': 't7',
            'input': {'original': [12, 18, 25, 31], 'replacements': [[2, 26], [3, 33]], 'threshold': 26},
            'expected': expected, 'actual': actual,
            'downstream_expected': expected_summaries, 'downstream_actual': summaries,
            'code_paths': ['revision/publication.py', 'reader/blocks.py', 'quality/reconcile.py',
                           'revision/finalize.py', 'reports/history.py'],
            'oracle': '手算四块值域与大于等于 26 的原块明细，两块各四字节，归位后为零。',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
