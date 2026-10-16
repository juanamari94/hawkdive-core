"""Local process implementation of the worker execution boundary."""

import asyncio
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from hawkdive.investigations import WorkerInput


def process_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Pass OS runtime settings and explicitly supplied execution configuration."""
    keys = ('PATH', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT',
            'SYSTEMDRIVE', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE')
    environment = {key: os.environ[key] for key in keys if key in os.environ}
    environment.update({'PYTHONUTF8': '1', 'PYTHONUNBUFFERED': '1',
                        'LANGSMITH_TRACING': 'false', 'LANGCHAIN_TRACING_V2': 'false'})
    environment.update(overrides or {})
    return environment


class Execution(Protocol):
    reference: str

    def updates(self) -> AsyncIterator[str]: ...
    async def wait(self) -> int: ...
    async def stop(self) -> int: ...


class ExecutionBackend(Protocol):
    def check_available(self) -> None: ...
    async def start(self, request: WorkerInput) -> Execution: ...


class ExecutionDisabled(RuntimeError):
    pass


class NullBackend:
    """Keep intake available while explicitly disabling worker execution."""

    def check_available(self) -> None:
        raise ExecutionDisabled('No worker command is configured')

    async def start(self, request: WorkerInput) -> Execution:
        raise ExecutionDisabled('No worker command is configured')


class ProcessExecution:
    def __init__(self, process: asyncio.subprocess.Process, *, cleanup: Callable[[], Awaitable[None]] | None = None) -> None:
        self.process = process
        self.reference = f'process:{process.pid}'
        self.stderr = asyncio.create_task(self._read_stderr())
        self.cleanup = cleanup
        self.cleanup_task: asyncio.Task[None] | None = None

    async def _read_stderr(self) -> str:
        # Drain continuously so stderr cannot block the child. Keep only a short diagnostic.
        saved = bytearray()
        while chunk := await self.process.stderr.read(4096):
            saved.extend(chunk[:max(0, 8192 - len(saved))])
        return saved.decode('utf-8', errors='replace')

    async def updates(self) -> AsyncIterator[str]:
        while line := await self.process.stdout.readline():
            yield line.decode('utf-8')

    async def wait(self) -> int:
        code = await self.process.wait()
        await self.stderr
        if self.cleanup is not None:
            if self.cleanup_task is None:
                self.cleanup_task = asyncio.create_task(self.cleanup())
            await asyncio.shield(self.cleanup_task)
        return code

    async def stop(self) -> int:
        async def discard_output() -> None:
            while await self.process.stdout.read(4096):
                pass

        drain = asyncio.create_task(discard_output())
        if self.process.returncode is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
        try:
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
            return await self.wait()
        finally:
            await drain


class ProcessBackend:
    def __init__(self, command: list[str], *, environment: dict[str, str] | None = None,
                 cleanup: Callable[[WorkerInput], Awaitable[None]] | None = None) -> None:
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError('Worker command must be a nonempty list of arguments')
        self.command = command
        self.environment = process_environment(environment)
        self.cleanup = cleanup

    def check_available(self) -> None:
        return None

    async def start(self, request: WorkerInput) -> ProcessExecution:
        process = await asyncio.create_subprocess_exec(
            *self.command, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env=self.environment,
        )
        cleanup_handler = self.cleanup

        async def cleanup_execution() -> None:
            if cleanup_handler is not None:
                await cleanup_handler(request)

        execution = ProcessExecution(process, cleanup=cleanup_execution if cleanup_handler else None)
        try:
            process.stdin.write((request.model_dump_json() + '\n').encode('utf-8'))
            await process.stdin.drain()
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            # A child that exits immediately still needs its exit code recorded.
            pass
        return execution
