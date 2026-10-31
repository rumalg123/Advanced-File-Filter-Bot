"""Docker setup must work offline and preserve its build-time dependencies."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('installer_status', [0, 73])
def test_docker_setup_does_not_reinstall_packages(tmp_path, installer_status):
    root = Path(__file__).resolve().parents[1]
    shutil.copy2(root / 'start.sh', tmp_path / 'start.sh')
    (tmp_path / 'requirements.txt').write_text('wzgram\n')
    fake_bin = tmp_path / 'bin'
    fake_bin.mkdir()
    marker = tmp_path / 'installer-called'
    (fake_bin / 'python3').write_text('#!/bin/sh\nprintf "3.13\\n"\n')
    (fake_bin / 'pip').write_text(
        '#!/bin/sh\nprintf called > "$QA_STARTUP_PIP_MARKER"\n'
        f'exit {installer_status}\n')
    for file in fake_bin.iterdir():
        file.chmod(0o700)
    result = subprocess.run(
        ['bash', str(tmp_path / 'start.sh'), '--setup'], cwd=tmp_path,
        env={**os.environ, 'PATH': str(fake_bin) + os.pathsep + os.environ['PATH'],
             'IN_DOCKER': 'true', 'QA_STARTUP_PIP_MARKER': str(marker)},
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists(), 'Startup attempted to change image dependencies'
