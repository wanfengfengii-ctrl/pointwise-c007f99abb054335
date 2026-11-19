import json

from archive.importer import ingest
from archive.integrity import BlockIntegrityError
from archive.layout import BlockLayout
from archive.workspace import initialize_workspace
from demo import EXAMPLES, load_reel
from reader.cursor import next as read_next
from reader.tasks import open as open_task
from reports.issue import report
from tests.support import WorkspaceCase, raw, scenario


class IntakeTests(WorkspaceCase):
    def test_t1_intake_in_order(self):
        reel = self.seed()
        task = open_task(self.workspace, reel.reel_id)
        self.assertEqual(task.version, 1)
        self.assertIsNone(task.source_request)
        output = self.read(task, 2) + self.read(task, 2)
        self.assertEqual(output, [(0, 12), (1, 18), (2, 25), (3, 31)])
        self.assertEqual(self.read(task), [])
        result = report(self.workspace, task_id=task.task_id, threshold=25)
        downstream = [result['range'], result['hits'], result['count']]
        expected = [[12, 31], [{'block_no': 2, 'value': 25}, {'block_no': 3, 'value': 31}], 2]
        self.assertEqual(downstream, expected)
        scenario('t1', {'blocks_hex': ['0c000000', '12000000', '19000000', '1f000000'], 'limit': 2},
                 [(0, 12), (1, 18), (2, 25), (3, 31)], output, expected, downstream,
                 ['archive/importer.py', 'reader/cursor.py', 'quality/reconcile.py'],
                 '按四块小端样例手算读值、范围及阈值 25 的明细。')
        for invalid_limit in (0, -1, True, 1.5, '2'):
            with self.subTest(limit=invalid_limit), self.assertRaises(ValueError):
                read_next(self.workspace, task.task_id, invalid_limit)
        with self.assertRaises(LookupError):
            read_next(self.workspace, 900, 1)

    def test_t1_batch_read_atomic(self):
        reel = self.seed()
        task = open_task(self.workspace, reel.reel_id)
        base = self.workspace.media / reel.base_name
        with base.open('r+b') as stream:
            stream.seek(4)
            stream.write(raw(99))
        with self.assertRaisesRegex(BlockIntegrityError, 'block 1'):
            self.read(task, 2)
        self.assertEqual(self.scalar('SELECT cursor FROM tasks WHERE task_id = ?', (task.task_id,)), 0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM observations'), 0)
        with base.open('r+b') as stream:
            stream.seek(4)
            stream.write(raw(18))
        self.reopen()
        self.assertEqual(self.read(task, 2), [(0, 12), (1, 18)])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM observations'), 2)
        self.assertEqual(self.read(task), [(2, 25), (3, 31)])

    def test_t1_initialize_preserves_data(self):
        sample = self.scratch / 'incoming-reel.json'
        sample.write_bytes((EXAMPLES / 'reel.json').read_bytes())
        reel = ingest(self.workspace, *load_reel(sample))
        task = open_task(self.workspace, reel.reel_id)
        self.assertEqual(self.read(task, 2), [(0, 12), (1, 18)])
        changed_input = json.loads(sample.read_text(encoding='utf-8'))
        changed_input['blocks_hex'][2] = '63000000'
        sample.write_text(json.dumps(changed_input), encoding='utf-8')
        initialize_workspace(self.workspace)
        initialize_workspace(self.workspace)
        self.reopen()
        self.assertEqual(self.read(task), [(2, 25), (3, 31)])
        self.assertEqual(report(self.workspace, task_id=task.task_id, threshold=25)['count'], 2)

    def test_t2_bad_input(self):
        _, layout, blocks, checks = load_reel(EXAMPLES / 'reel.json')
        for name, given_layout, given_blocks, given_checks in (
            ('empty', BlockLayout(0, 4), [], []),
            ('bad-width', BlockLayout(4, 0), blocks, checks),
            ('missing', layout, blocks[:-1], checks),
            ('short', layout, [b'\x0c', *blocks[1:]], checks),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    ingest(self.workspace, name, given_layout, given_blocks, given_checks)
                with self.assertRaises(LookupError):
                    open_task(self.workspace, name)
        with self.assertRaises(ValueError):
            ingest(self.workspace, '', layout, blocks, checks)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM reels'), 0)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM tasks'), 0)

    def test_t2_late_block(self):
        reel_id, layout, blocks, checks = load_reel(EXAMPLES / 'reel.json')
        checks[-1] = '0' * 64
        with self.assertRaisesRegex(BlockIntegrityError, 'block 3'):
            ingest(self.workspace, reel_id, layout, blocks, checks)
        self.reopen()
        with self.assertRaises(LookupError):
            open_task(self.workspace, reel_id)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM tasks'), 0)
        self.assertEqual(list(self.workspace.media.iterdir()), [])

    def test_t2_conflicting_reel(self):
        import hashlib

        reel = self.seed()
        changed = [raw(n) for n in (12, 18, 25, 99)]
        checks = [hashlib.sha256(block).hexdigest() for block in changed]
        with self.assertRaisesRegex(ValueError, 'already registered'):
            ingest(self.workspace, reel.reel_id, reel.layout, changed, checks)
        self.reopen()
        task = open_task(self.workspace, reel.reel_id)
        self.assertEqual(self.read(task), [(0, 12), (1, 18), (2, 25), (3, 31)])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM reels'), 1)
