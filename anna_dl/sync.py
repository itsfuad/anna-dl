from pathlib import Path
from typing import Dict, Any
from anna_dl.utils import load_json, save_json, existing_download

def sync_log_from_disk(output_dir: Path, queue_file: Path, log_file: Path) -> Dict[str, Any]:
    """
    Scans files on disk and reconciles them against queue entries and download log.
    Returns status statistics dictionary.
    """
    queue = load_json(queue_file, default=[])
    log_data = load_json(log_file, default={})

    synced = 0
    success = 0
    failed = 0

    for book in queue:
        item_key = f"{book.get('title', '')} - {book.get('author', '')}"
        path = existing_download(book, output_dir)
        found = path is not None
        if path:
            log_data[item_key] = {
                'status': 'SUCCESS', 'path': str(path), 'bytes': path.stat().st_size
            }
            synced += 1
            success += 1

        if not found:
            if log_data.get(item_key, {}).get('status') == 'SUCCESS':
                log_data[item_key] = {'status': 'FAILED'}
            if log_data.get(item_key, {}).get('status') == 'FAILED':
                failed += 1

    save_json(log_file, log_data)

    total = len(queue)
    not_found = total - success - failed

    return {
        'total': total,
        'success': success,
        'failed': failed,
        'not_found': not_found,
        'remaining': max(0, total - success),
        'synced': synced
    }
