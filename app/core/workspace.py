from pathlib import Path

FileTreeNode = dict[str, object]


class WorkspaceManager:
    def __init__(self) -> None:
        self.root = Path(__file__).resolve().parents[2] / "workspaces"

    def init_workspace(self, session_id: int) -> str:
        workspace = self._workspace_path(session_id)
        (workspace / "src").mkdir(parents=True, exist_ok=True)
        (workspace / "tests").mkdir(parents=True, exist_ok=True)
        return str(workspace)

    def write_file(self, session_id: int, relative_path: str, content: str) -> None:
        path = self._resolve(session_id, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_file(self, session_id: int, relative_path: str) -> str:
        path = self._resolve(session_id, relative_path)
        if not path.exists():
            raise FileNotFoundError(relative_path)
        return path.read_text(encoding="utf-8")

    def list_files_tree(self, session_id: int) -> list[FileTreeNode]:
        workspace = Path(self.init_workspace(session_id))
        return [self._node(path, workspace) for path in sorted(workspace.iterdir(), key=_sort_key)]

    def _workspace_path(self, session_id: int) -> Path:
        return (self.root / f"session_{session_id}").resolve()

    def _resolve(self, session_id: int, relative_path: str) -> Path:
        workspace = Path(self.init_workspace(session_id))
        path = (workspace / relative_path).resolve()
        if workspace != path and workspace not in path.parents:
            raise ValueError("Path escapes workspace")
        return path

    def _node(self, path: Path, workspace: Path) -> FileTreeNode:
        relative = path.relative_to(workspace).as_posix()
        if path.is_dir():
            return {
                "name": path.name,
                "path": relative,
                "type": "directory",
                "children": [
                    self._node(child, workspace)
                    for child in sorted(path.iterdir(), key=_sort_key)
                ],
            }
        return {
            "name": path.name,
            "path": relative,
            "type": "file",
        }


def _sort_key(path: Path) -> tuple[int, str]:
    return (1 if path.is_file() else 0, path.name.lower())
