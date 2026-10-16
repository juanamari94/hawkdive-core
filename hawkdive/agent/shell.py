"""Command runner and one Docker sandbox per investigation attempt."""

import asyncio
from uuid import UUID

from pydantic import BaseModel, JsonValue

from hawkdive.execution import process_environment


class CommandResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool = False
    timed_out: bool = False


async def run_command(command: list[str], *, timeout: float, output_limit: int = 12000) -> CommandResult:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env=process_environment(),
    )
    truncated = False

    async def capture(stream: asyncio.StreamReader) -> str:
        nonlocal truncated
        saved = bytearray()
        while chunk := await stream.read(4096):
            remaining = max(0, output_limit - len(saved))
            saved.extend(chunk[:remaining])
            truncated |= len(chunk) > remaining
        return saved.decode('utf-8', errors='replace')

    stdout = asyncio.create_task(capture(process.stdout))
    stderr = asyncio.create_task(capture(process.stderr))
    timed_out = False
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except TimeoutError:
        timed_out = True
        if process.returncode is None:
            process.kill()
        await process.wait()
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        await asyncio.gather(stdout, stderr)
        raise
    return CommandResult(stdout=await stdout, stderr=await stderr, exit_code=process.returncode,
                         truncated=truncated, timed_out=timed_out)


class DockerSandbox:
    def __init__(self, attempt_id: UUID, *, image: str, command_timeout: int = 30) -> None:
        self.name = f'hawkdive-agent-{attempt_id.hex}'
        self.volume = f'hawkdive-work-{attempt_id.hex}'
        self.image = image
        self.command_timeout = command_timeout
        self.created = False

    async def start(self) -> None:
        result = await run_command([
            'docker', 'create', '--name', self.name, '--label', 'hawkdive.agent-sandbox=true',
            '--user', '1000:1000', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--cpus', '1', '--memory', '512m',
            '--pids-limit', '128', '--tmpfs', '/tmp:rw,nosuid,size=64m',
            '--mount', f'type=volume,source={self.volume},target=/workspace',
            '--workdir', '/workspace', self.image,
        ], timeout=30)
        if result.exit_code != 0 or result.timed_out:
            # The create request may have reached Docker even when its client timed out.
            await self.remove()
            raise RuntimeError('Sandbox creation failed; check Docker and the configured sandbox image')
        self.created = True
        try:
            result = await run_command(['docker', 'start', self.name], timeout=30)
            if result.exit_code != 0 or result.timed_out:
                raise RuntimeError('Sandbox startup failed')
        except BaseException:
            await self.close()
            raise

    async def execute(self, command: str) -> dict[str, JsonValue]:
        if not self.created:
            raise RuntimeError('Sandbox is not running')
        try:
            result = await run_command(
                ['docker', 'exec', '--workdir', '/workspace', self.name, 'bash', '-lc', command],
                timeout=self.command_timeout,
            )
        except BaseException:
            await self.close()
            raise
        if result.timed_out:
            # Killing the CLI alone would leave the shell command running in the container.
            await self.close()
            raise RuntimeError('Shell command timed out; its sandbox was stopped')
        return result.model_dump(mode='json')

    async def remove(self) -> None:
        result = await run_command(['docker', 'rm', '--force', self.name], timeout=15)
        if result.timed_out or (result.exit_code != 0 and 'No such container' not in result.stderr):
            raise RuntimeError(f'Could not confirm sandbox removal: {self.name}')
        self.created = False

    async def close(self) -> None:
        if self.created:
            await self.remove()
        # Retain the attempt's volume for scratchpad/source inspection.
