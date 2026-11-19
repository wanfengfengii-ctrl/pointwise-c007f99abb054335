import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from archive.importer import ingest
from archive.session import open_archive
from archive.workspace import work_transaction
from demo import EXAMPLES, load_correction, load_reel
from reader.cursor import next as read_next
from reader.release import finish
from revision.publication import amend


PROJECT = Path(__file__).resolve().parents[1]
CHECKPOINT_EXIT = 73


def raw(value):
    return value.to_bytes(4, 'little', signed=True)


def pairs(observations):
    return [(item.block_no, item.value) for item in observations]


def scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    record = {'case_id': case_id, 'input': inputs, 'expected': expected, 'actual': actual,
              'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
              'code_paths': paths, 'oracle': oracle}
    print('POINTWISE_SCENARIO ' + json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='scan-reel-test-')
        self.addCleanup(temporary.cleanup)
        self.scratch = Path(temporary.name)
        self.root = self.scratch / 'archive'
        self.workspace = open_archive(self.root)

    def reopen(self):
        self.workspace = open_archive(self.root)
        return self.workspace

    def seed(self):
        return ingest(self.workspace, *load_reel(EXAMPLES / 'reel.json'))

    def correction(self):
        return load_correction(EXAMPLES / 'correction.json')

    def read(self, task, limit=4):
        return pairs(read_next(self.workspace, task.task_id, limit))

    def scalar(self, sql, parameters=()):
        with work_transaction(self.workspace) as database:
            return database.execute(sql, parameters).fetchone()[0]

    def interrupt(self, action, checkpoint, task_id=None):
        command = [sys.executable, '-B', '-m', 'tests.support', action, str(self.root), checkpoint]
        if task_id is not None:
            command.append(str(task_id))
        result = subprocess.run(command, cwd=PROJECT, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, CHECKPOINT_EXIT, result.stdout + result.stderr)
        self.assertIn('CHECKPOINT ' + checkpoint, result.stdout.splitlines())


def install_dual_version(workspace):
    """Install media and catalogue facts directly, without running ingest, amend or next."""
    fixture = json.loads((Path(__file__).parent / 'dual_version.json').read_text(encoding='utf-8'))
    reel_id = fixture['reel_id']
    request_id = fixture['request_id']
    base_name = 'base-' + hashlib.sha256(reel_id.encode()).hexdigest() + '.bin'
    fix_name = 'fix-' + hashlib.sha256(request_id.encode()).hexdigest() + '.bin'
    with work_transaction(workspace) as database:
        (workspace.media / base_name).write_bytes(bytes.fromhex(fixture['base_hex']))
        (workspace.media / fix_name).write_bytes(bytes.fromhex(fixture['correction_hex']))
        database.execute(
            'INSERT INTO reels(reel_id, block_count, block_width, base_name, original_checks) '
            'VALUES (?, 4, 4, ?, ?)', (reel_id, base_name, json.dumps(fixture['original_checks'])),
        )
        database.execute(
            'INSERT INTO changes(request_id, reel_id, parent_version, version, identity, state) '
            "VALUES (?, ?, 1, 2, ?, 'published')", (request_id, reel_id, fixture['identity']),
        )
        database.executemany(
            'INSERT INTO change_blocks(request_id, block_no, slot, digest) VALUES (?, ?, ?, ?)',
            [(request_id, *entry) for entry in fixture['slots']],
        )
        database.execute('INSERT INTO tasks(task_id, reel_id, version, cursor) VALUES (?, ?, 1, 2)',
                         (fixture['old_task'], reel_id))
        database.execute('INSERT INTO tasks(task_id, reel_id, version, source_request) VALUES (?, ?, 2, ?)',
                         (fixture['new_task'], reel_id, request_id))
        database.executemany('INSERT INTO observations(task_id, block_no, reading) VALUES (?, ?, ?)',
                             [(fixture['old_task'], 0, 'c'), (fixture['old_task'], 1, '12')])
    return fixture['old_task'], fixture['new_task']


def _worker(arguments):
    action, root, target, *rest = arguments
    workspace = open_archive(root)

    def checkpoint(event):
        if event == target:
            print('CHECKPOINT ' + event, flush=True)
            os._exit(CHECKPOINT_EXIT)

    if action == 'amend' and not rest:
        amend(workspace, *load_correction(EXAMPLES / 'correction.json'), checkpoint=checkpoint)
    elif action == 'finish' and len(rest) == 1:
        finish(workspace, int(rest[0]), checkpoint=checkpoint)
    else:
        raise ValueError('unknown checkpoint worker invocation')
    raise RuntimeError(f'operation returned before checkpoint {target!r}')


if __name__ == '__main__':
    _worker(sys.argv[1:])
