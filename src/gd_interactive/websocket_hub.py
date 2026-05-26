"""WebSocket connection pool + file watcher for real-time updates."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent


class ConnectionPool:
    """Manage WebSocket connections grouped by project_dir."""
    
    def __init__(self):
        self.connections: dict[str, list[Any]] = {}  # project_dir -> [websocket, ...]
    
    def add(self, project_dir: str, websocket: Any) -> None:
        """Add a WebSocket connection for a project."""
        if project_dir not in self.connections:
            self.connections[project_dir] = []
        self.connections[project_dir].append(websocket)
    
    def remove(self, project_dir: str, websocket: Any) -> None:
        """Remove a WebSocket connection."""
        if project_dir in self.connections:
            try:
                self.connections[project_dir].remove(websocket)
            except ValueError:
                pass
            if not self.connections[project_dir]:
                del self.connections[project_dir]
    
    async def broadcast(self, project_dir: str, event_type: str, data: Any) -> None:
        """Broadcast event to all connections for a project."""
        if project_dir not in self.connections:
            return
        
        message = json.dumps({"type": event_type, "data": data})
        dead_connections = []
        
        for ws in self.connections[project_dir]:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.append(ws)
        
        # Clean up dead connections
        for ws in dead_connections:
            self.remove(project_dir, ws)


class ProjectFileWatcher(FileSystemEventHandler):
    """Watch project files and trigger broadcasts."""
    
    def __init__(self, project_dir: Path, pool: ConnectionPool, loop: asyncio.AbstractEventLoop):
        self.project_dir = project_dir
        self.pool = pool
        self.loop = loop
    
    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        
        path = Path(event.src_path)
        
        # Watch for belief snapshot updates
        if path.name == "belief_snapshot.json" and "runs" in path.parts:
            asyncio.run_coroutine_threadsafe(
                self.pool.broadcast(str(self.project_dir), "graph_update", {"trigger": "belief_update"}),
                self.loop
            )
        
        # Watch for cycle state changes
        if path.name == "cycle_state.json" and ".gaia" in path.parts:
            asyncio.run_coroutine_threadsafe(
                self.pool.broadcast(str(self.project_dir), "execution_status", {"trigger": "cycle_state"}),
                self.loop
            )


def start_watcher(project_dir: Path, pool: ConnectionPool, loop: asyncio.AbstractEventLoop) -> Observer:
    """Start watching a project directory for file changes."""
    observer = Observer()
    handler = ProjectFileWatcher(project_dir, pool, loop)
    
    # Watch .gaia/ and runs/ directories
    gaia_dir = project_dir / ".gaia"
    runs_dir = project_dir / "runs"
    
    if gaia_dir.exists():
        observer.schedule(handler, str(gaia_dir), recursive=True)
    if runs_dir.exists():
        observer.schedule(handler, str(runs_dir), recursive=True)
    
    observer.start()
    return observer
