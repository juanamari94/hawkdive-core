import asyncio
import os
import sys
from uuid import uuid4

import pytest

from hawkdive.agent.shell import DockerSandbox, run_command


def test_shell_command_returns_bounded_output_and_exit_status():
    result = asyncio.run(run_command([
        sys.executable, '-c', 'import sys; print("x" * 20000); print("problem", file=sys.stderr); sys.exit(4)',
    ], timeout=5, output_limit=1000))
    assert result.exit_code == 4
    assert len(result.stdout) == 1000
    assert 'problem' in result.stderr
    assert result.truncated is True


def test_shell_command_does_not_receive_application_credentials(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'model-secret')
    monkeypatch.setenv('HAWKDIVE_GRAFANA_ACCESS_TOKEN', 'mcp-secret')
    result = asyncio.run(run_command([
        sys.executable, '-c', 'import os; print(os.getenv("OPENROUTER_API_KEY")); print(os.getenv("HAWKDIVE_GRAFANA_ACCESS_TOKEN"))',
    ], timeout=5))
    assert result.stdout.splitlines() == ['None', 'None']


def test_command_timeout_terminates_the_client_process():
    result = asyncio.run(run_command([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=0.1))
    assert result.timed_out is True
    assert result.exit_code != 0


@pytest.mark.skipif(os.getenv('HAWKDIVE_TEST_DOCKER') != '1', reason='Requires a running Docker engine and the sandbox image')
def test_docker_sandbox_preserves_files_and_isolates_attempts(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'model-secret')
    monkeypatch.setenv('HAWKDIVE_GRAFANA_ACCESS_TOKEN', 'mcp-secret')

    async def run():
        sandboxes = [DockerSandbox(uuid4(), image=os.getenv('HAWKDIVE_SANDBOX_IMAGE', 'hawkdive-sandbox:local')) for _ in range(2)]
        try:
            for sandbox in sandboxes:
                await sandbox.start()
            assert (await sandboxes[0].execute('printf hello > note.txt'))['exit_code'] == 0
            assert (await sandboxes[0].execute('cat note.txt'))['stdout'] == 'hello'
            assert (await sandboxes[1].execute('test ! -e note.txt'))['exit_code'] == 0
            assert (await sandboxes[0].execute(
                'python -c "import os; assert not os.getenv(\'OPENROUTER_API_KEY\'); assert not os.getenv(\'HAWKDIVE_GRAFANA_ACCESS_TOKEN\')"',
            ))['exit_code'] == 0
        finally:
            for sandbox in sandboxes:
                await sandbox.close()
                await run_command(['docker', 'volume', 'rm', sandbox.volume], timeout=15)

    asyncio.run(run())
