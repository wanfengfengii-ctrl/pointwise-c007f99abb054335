from collections.abc import Callable

from archive.catalog import get_reel
from archive.workspace import Workspace, work_transaction
from reader.tasks import get_task
from revision.finalize import try_finalization


def finish(
    workspace: Workspace, task_id: int, *, checkpoint: Callable[[str], None] | None = None,
) -> None:
    with work_transaction(workspace) as database:
        task = get_task(database, task_id)
        reel = get_reel(database, task.reel_id)
        if task.cursor != reel.layout.block_count:
            raise ValueError('task has unread blocks')
        if not task.released:
            database.execute('UPDATE tasks SET released = 1 WHERE task_id = ?', (task_id,))
    try_finalization(workspace, task.reel_id, checkpoint=checkpoint)
