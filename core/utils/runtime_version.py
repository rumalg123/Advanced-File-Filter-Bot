"""Version information for Git checkouts and source-only container updates."""
import json
import logging
from pathlib import Path
import subprocess

logger = logging.getLogger(__name__)
REVISION_FILE = '.runtime_revision.json'


def get_runtime_version():
    """Prefer the revision actually applied by the updater over a host checkout."""
    revision = Path(REVISION_FILE)
    if revision.is_file():
        try:
            info = json.loads(revision.read_text(encoding='utf-8'))
            if all(isinstance(info[key], str) for key in ('hash', 'full_hash', 'date', 'message')):
                return info
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning('Cannot read applied update revision', exc_info=True)

    if not (Path('.git').is_file() or Path('.git/HEAD').is_file()):
        return None
    try:
        def git(*args):
            return subprocess.run(['git', *args], capture_output=True, text=True,
                                  check=True, timeout=10).stdout.strip()
        commit = git('rev-parse', 'HEAD')
        date, message = git('log', '-1', '--format=%cd|%s', '--date=format:%Y-%m-%d %H:%M').split('|', 1)
        return {'hash': commit[:7], 'full_hash': commit, 'date': date,
                'message': message, 'has_changes': bool(git('status', '--porcelain'))}
    except (OSError, ValueError, subprocess.SubprocessError):
        logger.warning('Cannot read Git version', exc_info=True)
        return None
