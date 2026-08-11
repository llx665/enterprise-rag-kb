"""轻量级后台任务管理器。

开发环境下用 asyncio.create_task 在进程内异步执行文档处理。
生产环境可替换为 Celery / Redis 队列（里程碑 6 优化点），接口保持一致。
"""
import asyncio

from .document_service import process_document

_tasks: set[asyncio.Task] = set()


def submit_document(doc_id: int) -> None:
    """提交文档处理任务到后台执行。"""
    task = asyncio.create_task(process_document(doc_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
