from archive.catalog import get_reel
from archive.workspace import Workspace, work_transaction
from reader.blocks import read_task_block
from reader.observations import Observation, record_observations
from reader.tasks import get_task
from revision.journal import correction_slots, get_active_change


def next(workspace: Workspace, task_id: int, limit: int) -> tuple[Observation, ...]:
    if type(limit) is not int or limit <= 0:
        raise ValueError('read limit must be a positive integer')
    with work_transaction(workspace) as database:
        task = get_task(database, task_id)
        reel = get_reel(database, task.reel_id)
        stop = min(reel.layout.block_count, task.cursor + limit)
        if task.cursor == stop:
            return ()
        active = get_active_change(database, task.reel_id)
        slots = {} if active is None else correction_slots(database, active.request_id)
        batch = tuple(
            Observation(block_no, read_task_block(database, workspace, reel, task, block_no, active, slots))
            for block_no in range(task.cursor, stop)
        )
        record_observations(database, task_id, batch)
        database.execute('UPDATE tasks SET cursor = ? WHERE task_id = ?', (stop, task_id))
        return batch
