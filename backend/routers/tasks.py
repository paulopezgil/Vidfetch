"""Task status, SSE progress stream, and cancellation endpoints."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..models.schemas import TaskOut
from ..services.task_manager import TERMINAL_STATUSES, manager

router = APIRouter(tags=["tasks"])


@router.get("/api/tasks", response_model=list[TaskOut])
async def list_tasks() -> list[dict]:
    """Return the currently active (non-terminal) tasks."""
    return manager.list_active()


@router.get("/api/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: str) -> dict:
    task = manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task.to_dict()


@router.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request):
    """Server-Sent Events stream for a task's progress.

    The stream yields a JSON snapshot whenever the task's version changes
    (about every progress tick), then a ``done`` event at a terminal state.
    """
    async def event_stream():
        last_version: int | None = None
        while True:
            if await request.is_disconnected():
                break
            task = manager.get_task(task_id)
            if task is None:
                yield "event: error\ndata: " + json.dumps(
                    {"error": "Task not found."}
                ) + "\n\n"
                break
            snap = task.to_dict()
            if task.version != last_version:
                yield "data: " + json.dumps(snap) + "\n\n"
                last_version = task.version
            if task.status in TERMINAL_STATUSES:
                yield "event: done\ndata: " + json.dumps(snap) + "\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict:
    if not manager.cancel_task(task_id):
        raise HTTPException(
            status_code=409, detail="Task not found or already finished."
        )
    return {"task_id": task_id, "cancelled": True}
