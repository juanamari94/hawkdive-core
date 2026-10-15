"""Local process implementation of the worker execution boundary."""

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from hawkdive.investigations import WorkerInput


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
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process
        self.reference = f'process:{process.pid}'
        self.stderr = asyncio.create_task(self._read_stderr())

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
                return await asyncio.wait_for(self.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
                return await self.wait()
        finally:
            await drain


class ProcessBackend:
    def __init__(self, command: list[str]) -> None:
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError('Worker command must be a nonempty list of arguments')
        self.command = command

    def check_available(self) -> None:
        return None

    async def start(self, request: WorkerInput) -> ProcessExecution:
        process = await asyncio.create_subprocess_exec(
            *self.command, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        execution = ProcessExecution(process)
        try:
            process.stdin.write((request.model_dump_json() + '\n').encode('utf-8'))
            await process.stdin.drain()
            process.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            # A child that exits immediately still needs its exit code recorded.
            pass
        return execution
