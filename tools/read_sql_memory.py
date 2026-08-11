from collections.abc import Generator
from typing import Any
import json
import logging
import os
import sys

from dify_plugin import Tool
from dify_plugin.config.logger_format import plugin_logger_handler
from dify_plugin.entities.tool import ToolInvokeMessage

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from service.context import ContextManager


class ReadSqlMemoryTool(Tool):
    """读取当前 Dify 会话中已成功执行的 SQL 记忆，供工作流解析追问上下文。"""

    MAX_WINDOW_SIZE = 10
    MAX_SQL_SUMMARY_LENGTH = 1600
    MAX_QUERY_LENGTH = 500

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(plugin_logger_handler)
        self._context_manager = ContextManager()

    @classmethod
    def _truncate(cls, value: Any, max_length: int) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= max_length else f"{text[:max_length]}..."

    @staticmethod
    def _query_context(metadata: Any) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            return {}
        value = metadata.get("query_context")
        return value if isinstance(value, dict) else {}

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        conversation_id = str(tool_parameters.get("conversation_id") or "").strip()
        user_id = self.runtime.user_id
        raw_window_size = tool_parameters.get("memory_window_size", 3)
        try:
            window_size = int(raw_window_size)
        except (TypeError, ValueError):
            window_size = 3
        window_size = min(max(window_size, 1), self.MAX_WINDOW_SIZE)

        self.logger.info(
            "SQL_MEMORY_CONTEXT_READ_START user_id=%r conversation_id=%r window_size=%s",
            user_id,
            conversation_id,
            window_size,
        )
        if not user_id or not conversation_id:
            self.logger.warning(
                "SQL_MEMORY_CONTEXT_READ_SKIPPED reason=missing_identity user_id=%r conversation_id=%r",
                user_id,
                conversation_id,
            )
            yield self.create_text_message(text=json.dumps({"history_turns": 0, "history": []}))
            return

        history = self._context_manager.get_conversation_history(
            user_id=user_id,
            conversation_id=conversation_id,
            window_size=window_size,
        )
        items = []
        for item in history:
            metadata = item.get("metadata") if isinstance(item, dict) else {}
            items.append(
                {
                    "query": self._truncate(item.get("query"), self.MAX_QUERY_LENGTH),
                    "sql": self._truncate(item.get("sql"), self.MAX_SQL_SUMMARY_LENGTH),
                    "query_context": self._query_context(metadata),
                }
            )

        payload = {
            "conversation_id": conversation_id,
            "history_turns": len(items),
            "history": items,
            "latest_context": items[-1]["query_context"] if items else {},
        }
        self.logger.info(
            "SQL_MEMORY_CONTEXT_READ_SUCCESS conversation_id=%r history_turns=%s has_latest_context=%s",
            conversation_id,
            len(items),
            bool(payload["latest_context"]),
        )
        yield self.create_text_message(text=json.dumps(payload, ensure_ascii=False))
