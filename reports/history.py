import sqlite3

from reports.manifest import ReportManifest, decode_manifest


def lookup_report(database: sqlite3.Connection, report_id: int) -> ReportManifest:
    if type(report_id) is not int or not 0 < report_id <= 2**63 - 1:
        raise ValueError('invalid report number')
    row = database.execute('SELECT manifest FROM reports WHERE report_id = ?', (report_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown report {report_id}')
    return decode_manifest(row['manifest'])
