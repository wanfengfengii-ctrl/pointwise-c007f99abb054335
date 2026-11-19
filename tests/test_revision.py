from archive.workspace import work_transaction
from reader.cursor import next as read_next
from reader.release import finish
from reader.tasks import open as open_task
from reports.issue import report
from revision.media import correction_payload_size
from revision.publication import amend
from tests.support import WorkspaceCase, install_dual_version, pairs, raw, scenario


OLD = [(0, 12), (1, 18), (2, 25), (3, 31)]
NEW = [(0, 12), (1, 18), (2, 26), (3, 33)]


class RevisionTests(WorkspaceCase):
    def test_t3_two_shifts(self):
        reel = self.seed()
        white = open_task(self.workspace, reel.reel_id)
        self.assertEqual(self.read(white, 2), OLD[:2])
        receipt = amend(self.workspace, *self.correction())
        self.assertEqual(receipt.version, 2)
        self.reopen()
        night = open_task(self.workspace, reel.reel_id)
        self.assertEqual((white.version, night.version), (1, 2))
        night_prefix = self.read(night, 2)
        white_tail = self.read(white)
        night_tail = self.read(night)
        self.assertEqual(white_tail, OLD[2:])
        self.assertEqual(night_prefix + night_tail, NEW)
        night_report = report(self.workspace, task_id=night.task_id, threshold=26)
        self.assertEqual(night_report['source_request'], receipt.request_id)
        self.assertEqual(night_report['count'], 2)
        scenario('t3', {'old_cursor': 2, 'replacements': [[2, 26], [3, 33]]},
                 [OLD[2:], NEW], [white_tail, night_prefix + night_tail], 2, night_report['count'],
                 ['revision/publication.py', 'reader/tasks.py', 'reader/blocks.py', 'reports/issue.py'],
                 '采用手算父版末两块、新版全卷和阈值 26 的命中数。')

    def test_t3_dual_version_fixture(self):
        old_task, new_task = install_dual_version(self.workspace)
        self.reopen()
        self.assertEqual(pairs(read_next(self.workspace, old_task, 1)), [(2, 25)])
        self.assertEqual(pairs(read_next(self.workspace, new_task, 3)), NEW[:3])
        self.assertEqual(pairs(read_next(self.workspace, old_task, 4)), [(3, 31)])
        self.assertEqual(pairs(read_next(self.workspace, new_task, 4)), NEW[3:])
        self.assertEqual(report(self.workspace, task_id=old_task, threshold=26)['hits'],
                         [{'block_no': 3, 'value': 31}])

    def test_t4_preflight_before_interruption(self):
        reel = self.seed()
        white = open_task(self.workspace, reel.reel_id)
        self.assertEqual(self.read(white, 2), OLD[:2])
        _, request_id, _, replacements = self.correction()
        for suffix, parent, candidate in (
            ('bad-block', 1, [(4, raw(1))]),
            ('duplicate', 1, [replacements[0], replacements[0]]),
            ('short', 1, [(2, b'x')]),
            ('stale', 2, replacements),
            ('empty', 1, []),
        ):
            with self.subTest(suffix=suffix):
                with self.assertRaises(ValueError):
                    amend(self.workspace, reel.reel_id, suffix, parent, candidate)
                self.assertEqual(self.scalar('SELECT COUNT(*) FROM changes'), 0)
                self.assertEqual(list(self.workspace.media.glob('fix-*.bin')), [])
        self.interrupt('amend', 'first_payload_synced')
        self.reopen()
        self.assertEqual(correction_payload_size(self.workspace, request_id), 4)
        self.assertEqual(self.scalar("SELECT state FROM changes WHERE request_id = ?", (request_id,)), 'pending')
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM changes WHERE state <> 'pending'"), 0)
        with self.assertRaisesRegex(ValueError, 'different inputs'):
            amend(self.workspace, reel.reel_id, request_id, 1, [(2, raw(27)), (3, raw(33))])
        with self.assertRaisesRegex(ValueError, 'unfinalized'):
            amend(self.workspace, reel.reel_id, 'other-pending', 1, replacements)
        recovery_task = open_task(self.workspace, reel.reel_id)
        self.assertEqual(recovery_task.version, 1)
        before = self.read(recovery_task)
        self.assertEqual(before, OLD, 'prepublication parent values')
        finish(self.workspace, recovery_task.task_id)
        receipt = amend(self.workspace, *self.correction())
        self.assertEqual(receipt.version, 2)
        self.assertEqual(correction_payload_size(self.workspace, request_id), 8)
        night = open_task(self.workspace, reel.reel_id)
        after = self.read(night)
        old_tail = self.read(white)
        self.assertEqual(after, NEW, 'published new values')
        self.assertEqual(old_tail, OLD[2:], 'original task tail after replay')
        scenario('t4', {'checkpoint': 'first_payload_synced', 'old_cursor': 2}, OLD, before,
                 [NEW, OLD[2:]], [after, old_tail], ['revision/publication.py', 'reader/blocks.py'],
                 '原四块、完整替换及旧任务原序均独立于发布实现。')

    def test_t5_lost_reply_and_fingerprint_conflict(self):
        reel = self.seed()
        self.interrupt('amend', 'publication_committed')
        self.reopen()
        reel_id, request_id, parent, replacements = self.correction()
        night = open_task(self.workspace, reel.reel_id)
        self.assertEqual(night.version, 2)
        self.assertEqual(self.read(night), NEW)
        receipt = amend(self.workspace, reel_id, request_id, parent, reversed(replacements))
        self.assertEqual((receipt.reel_id, receipt.request_id, receipt.version), (reel_id, request_id, 2))
        with self.assertRaisesRegex(ValueError, 'different inputs'):
            amend(self.workspace, reel_id, request_id, parent, [(2, raw(27)), (3, raw(33))])
        self.assertEqual(amend(self.workspace, *self.correction()), receipt)
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM changes'), 1)
        self.assertEqual(self.read(open_task(self.workspace, reel_id)), NEW)
        self.assertEqual(correction_payload_size(self.workspace, request_id), 0)

    def test_t6_multiple_parent_tasks_and_next_batch_gate(self):
        reel = self.seed()
        first = open_task(self.workspace, reel.reel_id)
        second = open_task(self.workspace, reel.reel_id)
        self.assertEqual(self.read(second, 2), OLD[:2])
        receipt = amend(self.workspace, *self.correction())
        with work_transaction(self.workspace):
            self.assertEqual((self.workspace.media / reel.base_name).stat().st_size, 16)
            areas = list(self.workspace.media.glob('fix-*.bin'))
            self.assertEqual(len(areas), 1)
            self.assertEqual(areas[0].read_bytes(), raw(26) + raw(33))
        self.assertEqual(correction_payload_size(self.workspace, receipt.request_id), 8)
        self.assertEqual(self.read(first), OLD)
        finish(self.workspace, first.task_id)
        with self.assertRaisesRegex(ValueError, 'unfinalized'):
            amend(self.workspace, reel.reel_id, 'change-first', 2, [(0, raw(13))])
        self.assertEqual(self.scalar('SELECT COUNT(*) FROM changes'), 1)
        self.reopen()
        night = open_task(self.workspace, reel.reel_id)
        self.assertEqual(self.read(night, 1), NEW[:1])
        self.assertEqual(correction_payload_size(self.workspace, receipt.request_id), 8)
        self.assertEqual(self.read(second), OLD[2:])
        finish(self.workspace, second.task_id)
        self.assertEqual(correction_payload_size(self.workspace, receipt.request_id), 0)
        self.assertEqual(list(self.workspace.media.glob('fix-*.bin')), [])
        self.reopen()
        self.assertEqual(self.read(open_task(self.workspace, reel.reel_id)), NEW)
        self.assertEqual(self.read(night), NEW[1:])
        new_receipt = amend(self.workspace, reel.reel_id, 'change-first', 2, [(0, raw(13))])
        self.assertEqual(new_receipt.version, 3)
        self.assertEqual(self.read(open_task(self.workspace, reel.reel_id)), [(0, 13), *NEW[1:]])
        self.assertEqual(amend(self.workspace, *self.correction()), receipt)

    def test_t6_reopen_before_cleanup(self):
        reel = self.seed()
        white = open_task(self.workspace, reel.reel_id)
        receipt = amend(self.workspace, *self.correction())
        self.assertEqual(self.read(white), OLD)
        self.interrupt('finish', 'base_verified', white.task_id)
        self.assertEqual(self.scalar('SELECT state FROM changes'), 'cleanup')
        self.assertEqual(self.scalar('SELECT released FROM tasks WHERE task_id = ?', (white.task_id,)), 1)
        self.assertEqual((self.workspace.media / reel.base_name).read_bytes(),
                         b''.join(raw(value) for _, value in NEW))
        self.assertEqual(correction_payload_size(self.workspace, receipt.request_id), 8)
        self.reopen()
        self.assertEqual(self.scalar('SELECT state FROM changes'), 'finalized')
        self.assertEqual(correction_payload_size(self.workspace, receipt.request_id), 0)
        self.assertEqual(list(self.workspace.media.glob('fix-*.bin')), [])
        self.assertEqual(self.read(open_task(self.workspace, reel.reel_id)), NEW)
        followup = amend(self.workspace, reel.reel_id, 'after-cleanup', 2, [(3, raw(34))])
        self.assertEqual(followup.version, 3)

    def test_t6_reads_published_revision_during_partial_placement(self):
        reel = self.seed()
        white = open_task(self.workspace, reel.reel_id)
        receipt = amend(self.workspace, *self.correction())
        self.assertEqual(self.read(white), OLD)
        self.interrupt('finish', 'first_base_synced', white.task_id)
        self.assertEqual(self.scalar('SELECT state FROM changes'), 'placing')
        self.assertEqual((self.workspace.media / reel.base_name).read_bytes(),
                         raw(12) + raw(18) + raw(26) + raw(31))
        self.assertEqual(self.read(open_task(self.workspace, reel.reel_id)), NEW)
        self.reopen()
        self.assertEqual(self.read(open_task(self.workspace, reel.reel_id)), NEW)
        self.assertEqual(correction_payload_size(self.workspace, receipt.request_id), 0)

    def test_t6_recovers_after_unlink_before_terminal_commit(self):
        reel = self.seed()
        white = open_task(self.workspace, reel.reel_id)
        receipt = amend(self.workspace, *self.correction())
        self.assertEqual(self.read(white), OLD)
        self.interrupt('finish', 'correction_reclaimed', white.task_id)
        self.assertEqual(self.scalar('SELECT state FROM changes'), 'cleanup')
        self.assertEqual(correction_payload_size(self.workspace, receipt.request_id), 0)
        self.assertEqual(self.read(open_task(self.workspace, reel.reel_id)), NEW)
        self.reopen()
        self.assertEqual(self.scalar('SELECT state FROM changes'), 'finalized')
