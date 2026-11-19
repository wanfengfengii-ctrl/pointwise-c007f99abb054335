from hashlib import sha256

from archive.importer import ingest
from archive.layout import BlockLayout
from reader.release import finish
from reader.tasks import open as open_task
from reports.issue import report
from revision.publication import amend
from tests.support import WorkspaceCase, raw


class AuditTests(WorkspaceCase):
    def test_t7_sealed_history(self):
        reel = self.seed()
        old = open_task(self.workspace, reel.reel_id)
        self.assertEqual(self.read(old, 2), [(0, 12), (1, 18)])
        receipt = amend(self.workspace, *self.correction())
        new = open_task(self.workspace, reel.reel_id)
        self.assertEqual(self.read(old), [(2, 25), (3, 31)])
        self.assertEqual(self.read(new), [(0, 12), (1, 18), (2, 26), (3, 33)])
        old_report = report(self.workspace, task_id=old.task_id, threshold=26)
        finish(self.workspace, old.task_id)
        finish(self.workspace, new.task_id)
        new_report = report(self.workspace, task_id=new.task_id, threshold=26)
        self.assertEqual(old_report, {
            'report_id': 1, 'task_id': old.task_id, 'reel_id': reel.reel_id, 'version': 1,
            'source_request': None, 'threshold': 26, 'range': [12, 31],
            'hits': [{'block_no': 3, 'value': 31}], 'count': 1,
        })
        self.assertEqual(new_report, {
            'report_id': 2, 'task_id': new.task_id, 'reel_id': reel.reel_id, 'version': 2,
            'source_request': receipt.request_id, 'threshold': 26, 'range': [12, 33],
            'hits': [{'block_no': 2, 'value': 26}, {'block_no': 3, 'value': 33}], 'count': 2,
        })
        later = amend(self.workspace, reel.reel_id, 'later', 2, [(3, raw(19))])
        self.assertEqual(later.version, 3)
        self.reopen()
        self.assertEqual(report(self.workspace, report_id=new_report['report_id']), new_report)
        self.assertEqual(report(self.workspace, report_id=old_report['report_id']), old_report)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM reports'), 2)

    def test_t7_signed_range_and_no_hits(self):
        blocks = [raw(value) for value in (-7, 2, -1, 4)]
        ingest(self.workspace, 'signed-reel', BlockLayout(4, 4), blocks,
               [sha256(block).hexdigest() for block in blocks])
        task = open_task(self.workspace, 'signed-reel')
        self.assertEqual(self.read(task), [(0, -7), (1, 2), (2, -1), (3, 4)])
        result = report(self.workspace, task_id=task.task_id, threshold=5)
        self.assertEqual((result['range'], result['hits'], result['count']), ([-7, 4], [], 0))
        self.assertEqual(report(self.reopen(), report_id=result['report_id']), result)

    def test_t7_invalid_report_input(self):
        reel = self.seed()
        task = open_task(self.workspace, reel.reel_id)
        self.read(task)
        for threshold in (None, True, False, '26', 26.0):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                report(self.workspace, task_id=task.task_id, threshold=threshold)
        with self.assertRaises(LookupError):
            report(self.workspace, report_id=900)
        with self.assertRaises(LookupError):
            report(self.workspace, task_id=900, threshold=26)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM reports'), 0)

    def test_t8_early_finish_and_report_preserve_cursor(self):
        reel = self.seed()
        task = open_task(self.workspace, reel.reel_id)
        self.assertEqual(self.read(task, 2), [(0, 12), (1, 18)])
        with self.assertRaisesRegex(ValueError, 'unread'):
            finish(self.workspace, task.task_id)
        with self.assertRaisesRegex(ValueError, 'unread'):
            report(self.workspace, task_id=task.task_id, threshold=26)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM reports'), 0)
        self.assertEqual(self.scalar('SELECT cursor FROM tasks'), 2)
        self.assertEqual(self.scalar('SELECT released FROM tasks'), 0)
        self.reopen()
        self.assertEqual(self.read(task), [(2, 25), (3, 31)])
        finish(self.workspace, task.task_id)
        self.assertEqual(self.scalar('SELECT released FROM tasks'), 1)
        self.assertEqual(self.read(task), [])
        self.assertEqual(report(self.workspace, task_id=task.task_id, threshold=26)['count'], 1)
