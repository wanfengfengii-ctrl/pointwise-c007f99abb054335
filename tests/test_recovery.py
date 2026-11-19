from hashlib import sha256
from unittest import mock

from archive.importer import ingest_recoverable
from archive.integrity import BlockIntegrityError
from archive.layout import BlockLayout
from archive.workspace import work_transaction
from demo import EXAMPLES, check_witness, load_recoverable
from reader.release import finish
from reader.tasks import open as open_task
from reports.issue import report
from revision.media import correction_payload_size
from revision.publication import amend
from tests.support import WorkspaceCase, scenario


def byte(value):
    return bytes([value])


class RecoveryTests(WorkspaceCase):
    def load(self):
        return load_recoverable(EXAMPLES / 'recoverable.json')

    def seed_gap(self):
        reel_id, layout, blocks, checks, groups, _, _ = self.load()
        return ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, groups)

    def recovered(self, result):
        return [[item['block_no'], item['original_hex']] for item in result['recovered_blocks']]

    def check_report_witness(self, result, blocks, groups, width=1):
        for item in result['recovered_blocks']:
            check_witness(blocks, groups, item['block_no'], item['original_hex'],
                          item['group_ids'], width)

    def assert_unclaimable(self, reel_id):
        with self.assertRaises(LookupError):
            open_task(self.workspace, reel_id)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM reels'), 0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM recovered_blocks'), 0)

    def test_t9_recover_finalize_and_reclaim(self):
        reel_id, layout, blocks, checks, groups, correction, expected = self.load()
        gap = ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, groups)
        self.assertEqual(gap.initial_version, 1)
        day = open_task(self.workspace, gap.reel_id)
        self.assertEqual((day.version, day.source_request), (1, None))
        day_readings = self.read(day)
        self.assertEqual(day_readings, [(0, 12), (1, 18), (2, 25), (3, 31)])
        day_report = report(self.workspace, task_id=day.task_id, threshold=26)
        self.assertEqual(day_report['hits'], [{'block_no': 3, 'value': 31}])
        self.assertEqual(self.recovered(day_report), [[1, '12'], [2, '19'], [3, '1f']])
        self.assertEqual([item['group_ids'] for item in day_report['recovered_blocks']],
                         [['B', 'C'], ['A', 'B', 'C'], ['A', 'C']])
        self.check_report_witness(day_report, blocks, groups)
        request_id, parent, replacements = correction
        receipt = amend(self.workspace, gap.reel_id, request_id, parent, replacements)
        self.assertEqual(receipt.version, 2)
        finish(self.workspace, day.task_id)
        self.assertEqual(correction_payload_size(self.workspace, request_id), 0)
        self.reopen()
        night = open_task(self.workspace, gap.reel_id)
        self.assertEqual((night.version, night.source_request), (2, request_id))
        night_readings = self.read(night)
        self.assertEqual(night_readings, [(0, 12), (1, 18), (2, 25), (3, 33)])
        night_report = report(self.workspace, task_id=night.task_id, threshold=26)
        self.assertEqual(night_report['hits'], [{'block_no': 3, 'value': 33}])
        self.assertEqual(night_report['recovered_blocks'], day_report['recovered_blocks'])
        self.check_report_witness(night_report, blocks, groups)
        finish(self.workspace, night.task_id)
        self.reopen()
        self.assertEqual(report(self.workspace, report_id=day_report['report_id']), day_report)
        self.assertEqual(report(self.workspace, report_id=night_report['report_id']), night_report)
        scenario('t9', {'groups': [[g, n, p.hex()] for g, n, p in groups], 'threshold': 26},
                 [[(0, 12), (1, 18), (2, 25), (3, 31)], [(0, 12), (1, 18), (2, 25), (3, 33)]],
                 [day_readings, night_readings],
                 [[1, '12'], [2, '19'], [3, '1f']], self.recovered(night_report),
                 ['archive/importer.py', 'archive/recovery.py', 'reports/issue.py',
                  'reports/manifest.py'],
                 '联立三组异或方程手算缺块与见证，归位后首版回补清单不变。')

    def test_t9_underdetermined_rejected(self):
        reel_id, layout, blocks, checks, groups, _, _ = self.load()
        del groups[2]
        with self.assertRaisesRegex(ValueError, 'determine'):
            ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, groups)
        self.assert_unclaimable(reel_id)
        self.reopen()
        self.assert_unclaimable(reel_id)

    def test_t9_contradiction_rejected(self):
        reel_id, layout, blocks, checks, groups, _, _ = self.load()
        groups.append(('X', [1, 3], b'\x0c'))
        with self.assertRaisesRegex(ValueError, 'contradict'):
            ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, groups)
        self.assert_unclaimable(reel_id)

    def test_t9_checksum_mismatch_rejected_then_resubmitted(self):
        reel_id, layout, blocks, checks, groups, _, _ = self.load()
        groups[2] = ('C', [1, 2, 3], b'\x15')
        with self.assertRaisesRegex(BlockIntegrityError, 'block 1'):
            ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, groups)
        self.assert_unclaimable(reel_id)
        self.reopen()
        self.assertEqual(list(self.workspace.media.iterdir()), [])
        _, _, blocks, checks, groups, _, _ = self.load()
        gap = ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, groups)
        task = open_task(self.workspace, gap.reel_id)
        self.assertEqual(self.read(task), [(0, 12), (1, 18), (2, 25), (3, 31)])
        result = report(self.workspace, task_id=task.task_id, threshold=26)
        self.assertEqual(self.recovered(result), [[1, '12'], [2, '19'], [3, '1f']])

    def test_t9_witness_uses_first_version_arrived_bytes(self):
        reel_id, layout, blocks, checks, _, _, _ = self.load()
        groups = [('D', [0, 1, 2], b'\x07'), ('B', [2, 3], b'\x06'), ('C', [1, 2, 3], b'\x14')]
        gap = ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, groups)
        day = open_task(self.workspace, gap.reel_id)
        self.assertEqual(self.read(day), [(0, 12), (1, 18), (2, 25), (3, 31)])
        receipt = amend(self.workspace, gap.reel_id, 'fix-arrived', 1,
                        [(0, byte(13)), (3, byte(33))])
        finish(self.workspace, day.task_id)
        self.assertEqual(correction_payload_size(self.workspace, receipt.request_id), 0)
        self.reopen()
        night = open_task(self.workspace, gap.reel_id)
        self.assertEqual(self.read(night), [(0, 13), (1, 18), (2, 25), (3, 33)])
        result = report(self.workspace, task_id=night.task_id, threshold=26)
        recovered = {item['block_no']: item for item in result['recovered_blocks']}
        self.assertEqual(recovered[3]['original_hex'], '1f')
        self.assertEqual(recovered[3]['group_ids'], ['C', 'D'])
        self.check_report_witness(result, blocks, groups)

    def test_t9_failed_registration_leaves_no_trace(self):
        reel_id, layout, blocks, checks, groups, _, _ = self.load()
        with mock.patch('archive.importer.register_reel',
                        side_effect=OSError('injected media fault')):
            with self.assertRaises(OSError):
                ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, groups)
        self.assert_unclaimable(reel_id)
        self.assertEqual(len(list(self.workspace.media.iterdir())), 1)
        self.reopen()
        self.assertEqual(list(self.workspace.media.iterdir()), [])
        gap = ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, groups)
        task = open_task(self.workspace, gap.reel_id)
        self.assertEqual(self.read(task), [(0, 12), (1, 18), (2, 25), (3, 31)])
        result = report(self.workspace, task_id=task.task_id, threshold=26)
        self.assertEqual(self.recovered(result), [[1, '12'], [2, '19'], [3, '1f']])

    def test_t9_zero_missing_and_arrived_only_groups(self):
        layout = BlockLayout(4, 1)
        blocks = [byte(12), byte(18), byte(25), byte(31)]
        checks = [sha256(block).hexdigest() for block in blocks]
        groups = [('G', [0, 1], byte(12 ^ 18)), ('H', [0, 2, 3], byte(12 ^ 25 ^ 31))]
        reel = ingest_recoverable(self.workspace, 'full-reel', layout, blocks, checks, groups)
        task = open_task(self.workspace, reel.reel_id)
        self.assertEqual(self.read(task), [(0, 12), (1, 18), (2, 25), (3, 31)])
        result = report(self.workspace, task_id=task.task_id, threshold=26)
        self.assertNotIn('recovered_blocks', result)
        empty = ingest_recoverable(self.workspace, 'empty-groups', layout, blocks, checks, [])
        task = open_task(self.workspace, empty.reel_id)
        self.assertEqual(self.read(task), [(0, 12), (1, 18), (2, 25), (3, 31)])
        self.assertNotIn('recovered_blocks',
                         report(self.workspace, task_id=task.task_id, threshold=26))
        with self.assertRaisesRegex(ValueError, 'contradict'):
            ingest_recoverable(self.workspace, 'bad-parity', layout, blocks, checks,
                               [('G', [0, 1], byte(0))])
        with self.assertRaises(LookupError):
            open_task(self.workspace, 'bad-parity')

    def test_t9_plain_reel_report_has_no_recovery_section(self):
        reel = self.seed()
        task = open_task(self.workspace, reel.reel_id)
        self.read(task)
        result = report(self.workspace, task_id=task.task_id, threshold=26)
        self.assertNotIn('recovered_blocks', result)

    def test_t9_old_library_reopened(self):
        reel = self.seed()
        task = open_task(self.workspace, reel.reel_id)
        self.read(task)
        sealed = report(self.workspace, task_id=task.task_id, threshold=26)
        with work_transaction(self.workspace) as database:
            database.execute('DROP TABLE recovered_blocks')
        self.reopen()
        self.assertEqual(report(self.workspace, report_id=sealed['report_id']), sealed)
        self.assertNotIn('recovered_blocks', sealed)

    def test_t9_invalid_inputs(self):
        reel_id, layout, blocks, checks, groups, _, _ = self.load()
        for name, bad_groups in (
            ('empty-id', [('', [1], b'\x00')]),
            ('blank-id', [('  ', [1], b'\x00')]),
            ('non-text-id', [(7, [1], b'\x00')]),
            ('duplicate-id', [('A', [1], b'\x0b'), ('A', [2], b'\x06')]),
            ('no-blocks', [('E', [], b'\x00')]),
            ('duplicate-blocks', [('E', [1, 1], b'\x00')]),
            ('out-of-range', [('E', [4], b'\x00')]),
            ('negative', [('E', [-1], b'\x00')]),
            ('non-int-block', [('E', ['1'], b'\x00')]),
            ('bool-block', [('E', [True], b'\x00')]),
            ('short-parity', [('E', [1], b'')]),
            ('long-parity', [('E', [1], b'\x00\x00')]),
            ('text-parity', [('E', [1], '0b')]),
            ('not-a-triple', [('E', [1])]),
            ('none-numbers', [('E', None, b'\x00')]),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, bad_groups)
        for name, bad_check in (
            ('short-checksum', '0' * 63),
            ('upper-checksum', 'A' * 64),
            ('non-text-checksum', 0),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                ingest_recoverable(self.workspace, reel_id, layout, blocks,
                                   [*checks[:3], bad_check], groups)
        for name, bad_blocks in (
            ('text-block', [b'\x0c', '12', None, None]),
            ('bytearray-block', [b'\x0c', bytearray(b'\x12'), None, None]),
            ('short-block', [b'\x0c', b'\x12\x00', None, None]),
            ('wrong-count', blocks[:3]),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                ingest_recoverable(self.workspace, reel_id, layout, bad_blocks, checks, groups)
        bad_check = [*checks[:3], '0' * 64]
        with self.assertRaisesRegex(BlockIntegrityError, 'block 3'):
            ingest_recoverable(self.workspace, reel_id, layout, blocks, bad_check, groups)
        bad_check = ['0' * 64, *checks[1:]]
        with self.assertRaisesRegex(BlockIntegrityError, 'block 0'):
            ingest_recoverable(self.workspace, reel_id, layout, blocks, bad_check, groups)
        self.assert_unclaimable(reel_id)
        self.seed_gap()
        with self.assertRaisesRegex(ValueError, 'already registered'):
            ingest_recoverable(self.workspace, reel_id, layout, blocks, checks, groups)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM reels'), 1)
