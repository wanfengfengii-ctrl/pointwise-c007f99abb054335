import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.importer import ingest, ingest_recoverable
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


def load_recoverable(path: Path):
    data = json.loads(path.read_text(encoding='utf-8'))
    layout = BlockLayout(data['block_count'], data['block_width'])
    blocks = [None if block is None else bytes.fromhex(block) for block in data['blocks_hex']]
    groups = [(group_id, numbers, bytes.fromhex(parity))
              for group_id, numbers, parity in data['groups']]
    correction = data['correction']
    replacements = [(block_no, bytes.fromhex(payload))
                    for block_no, payload in correction['replacements']]
    request = (correction['request_id'], correction['parent_version'], replacements)
    return data['reel_id'], layout, blocks, data['checksums'], groups, request, data['expected']


def check_witness(blocks, groups, block_no, original_hex, group_ids, block_width):
    """Recompute a recovered block from its witness groups and the original submission.

    Cancels each listed group's arrived items with their first-version bytes,
    XORs the remaining equations, and requires exactly the recovered block on
    the left and its first-version bytes on the right.
    """
    by_id = {group_id: (numbers, parity) for group_id, numbers, parity in groups}
    left = set()
    right = bytearray(block_width)
    for group_id in group_ids:
        numbers, parity = by_id[group_id]
        left.symmetric_difference_update(numbers)
        for index, byte in enumerate(parity):
            right[index] ^= byte
    for number in tuple(left):
        arrived = blocks[number]
        if arrived is not None:
            left.discard(number)
            for index, byte in enumerate(arrived):
                right[index] ^= byte
    if left != {block_no} or bytes(right) != bytes.fromhex(original_hex):
        raise ValueError('witness does not reproduce the recovered first-version block')


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

        (gap_id, gap_layout, gap_blocks, gap_checks, gap_groups,
         (request_id, parent_version, replacements), gap_expected) = load_recoverable(
            EXAMPLES / 'recoverable.json')
        gap = ingest_recoverable(workspace, gap_id, gap_layout, gap_blocks, gap_checks, gap_groups)
        gap_day = open_task(workspace, gap.reel_id)
        day_values = [item.value for item in read_next(workspace, gap_day.task_id, gap_layout.block_count)]
        day_report = report(workspace, task_id=gap_day.task_id, threshold=gap_expected['threshold'])
        gap_receipt = amend(workspace, gap.reel_id, request_id, parent_version, replacements)
        finish(workspace, gap_day.task_id)
        reclaimed = correction_payload_size(workspace, gap_receipt.request_id)
        workspace = open_archive(directory)
        gap_night = open_task(workspace, gap.reel_id)
        night_gap_values = [item.value for item in read_next(workspace, gap_night.task_id,
                                                             gap_layout.block_count)]
        night_gap_report = report(workspace, task_id=gap_night.task_id,
                                  threshold=gap_expected['threshold'])
        finish(workspace, gap_night.task_id)
        workspace = open_archive(directory)
        gap_history = [report(workspace, report_id=result['report_id'])
                       for result in (day_report, night_gap_report)]
        for result in gap_history:
            for item in result['recovered_blocks']:
                check_witness(gap_blocks, gap_groups, item['block_no'], item['original_hex'],
                              item['group_ids'], gap_layout.block_width)
        gap_actual = {
            'versions': [gap_day.version, gap_night.version],
            'readings': [day_values, night_gap_values],
            'correction_bytes': reclaimed,
            'recovered': [[item['block_no'], item['original_hex']]
                          for item in night_gap_report['recovered_blocks']],
        }
        gap_wanted = {
            'versions': [1, 2],
            'readings': [gap_expected['original_values'], gap_expected['amended_values']],
            'correction_bytes': 0,
            'recovered': gap_expected['recovered_blocks_hex'],
        }
        gap_hits = [day_report['hits'], night_gap_report['hits']]
        wanted_hits = [gap_expected['original_hits'], gap_expected['amended_hits']]
        if (gap_actual != gap_wanted or gap_hits != wanted_hits
                or gap_history != [day_report, night_gap_report]
                or day_report['recovered_blocks'] != night_gap_report['recovered_blocks']):
            raise RuntimeError('recovered reel readings or sealed provenance did not match the sample ledger')
        print(json.dumps({'receipt': asdict(gap_receipt), 'reports': gap_history},
                         ensure_ascii=False, sort_keys=True))
        evidence = {
            'case_id': 't9',
            'input': {'arrived': ['0c'], 'groups': [[g, n, p.hex()] for g, n, p in gap_groups],
                      'replacements': [[3, 33]], 'threshold': gap_expected['threshold']},
            'expected': gap_wanted, 'actual': gap_actual,
            'downstream_expected': wanted_hits, 'downstream_actual': gap_hits,
            'code_paths': ['archive/importer.py', 'archive/recovery.py', 'reports/issue.py',
                           'reports/manifest.py', 'revision/finalize.py'],
            'oracle': '联立三组异或方程手算缺块 12、19、1f，归位后按封存报告核对首版回补清单与见证。',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
