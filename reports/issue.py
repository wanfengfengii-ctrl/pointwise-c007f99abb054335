from archive.catalog import get_reel
from archive.workspace import Workspace, work_transaction
from quality.reconcile import reconcile
from quality.thresholds import validate_threshold
from reader.observations import iter_observations
from reader.tasks import get_task
from reports.export import export_report
from reports.history import lookup_report
from reports.manifest import ReportManifest, build_manifest, encode_manifest


def issue_report(workspace: Workspace, task_id: int, threshold: int) -> ReportManifest:
    validate_threshold(threshold)
    with work_transaction(workspace) as database:
        task = get_task(database, task_id)
        reel = get_reel(database, task.reel_id)
        if task.cursor != reel.layout.block_count:
            raise ValueError('task has unread blocks')
        totals = reconcile(iter_observations(database, task_id), reel.layout.block_count, threshold)
        row = database.execute("INSERT INTO reports(task_id, manifest) VALUES (?, '')", (task_id,))
        manifest = build_manifest(row.lastrowid, task, totals)
        database.execute('UPDATE reports SET manifest = ? WHERE report_id = ?',
                         (encode_manifest(manifest), manifest.report_id))
        return manifest


def report(
    workspace: Workspace, *, task_id: int | None = None, threshold: int | None = None,
    report_id: int | None = None,
) -> dict:
    if report_id is not None:
        if task_id is not None or threshold is not None:
            raise ValueError('report lookup only accepts a report number')
        with work_transaction(workspace) as database:
            return export_report(lookup_report(database, report_id))
    if task_id is None:
        raise ValueError('report issuance requires a task number and a threshold')
    return export_report(issue_report(workspace, task_id, threshold))
