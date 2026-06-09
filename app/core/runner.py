import asyncio
import sys
from pathlib import Path

from app.core.workspace import WorkspaceManager


class AsyncCodeRunner:
    def __init__(self, workspace_manager: WorkspaceManager | None = None) -> None:
        self.workspace_manager = workspace_manager or WorkspaceManager()

    async def run_code(
        self,
        session_id: int,
        entry_point: str = "src/main.py",
        timeout: int = 5,
    ) -> tuple[bool, str]:
        workspace = Path(self.workspace_manager.init_workspace(session_id))
        script_path = (workspace / entry_point).resolve()
        if workspace != script_path and workspace not in script_path.parents:
            raise ValueError("Entry point escapes workspace")
        if not script_path.exists():
            raise FileNotFoundError(entry_point)

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            entry_point,
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return False, f"Timeout: execution exceeded {timeout} seconds"

        output = stdout.decode("utf-8", errors="replace").strip()
        error = stderr.decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            return False, error or output
        return True, output or "Success"
