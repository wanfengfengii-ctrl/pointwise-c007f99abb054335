from reports.manifest import ReportManifest


def export_report(manifest: ReportManifest) -> dict:
    payload = {
        'report_id': manifest.report_id,
        'task_id': manifest.task_id,
        'reel_id': manifest.reel_id,
        'version': manifest.version,
        'source_request': manifest.source_request,
        'threshold': manifest.threshold,
        'range': [manifest.minimum, manifest.maximum],
        'hits': [{'block_no': hit.block_no, 'value': hit.value} for hit in manifest.hits],
        'count': manifest.count,
    }
    if manifest.recovered_blocks is not None:
        payload['recovered_blocks'] = [
            {'block_no': item.block_no, 'original_hex': item.original_hex,
             'group_ids': list(item.group_ids)}
            for item in manifest.recovered_blocks
        ]
    return payload
