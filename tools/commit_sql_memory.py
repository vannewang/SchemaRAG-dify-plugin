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


class CommitSqlMemoryTool(Tool):
    """仅在 SQL 已通过校验并成功执行后写入当前会话记忆。"""

    MAX_QUERY_LENGTH = 10000
    MAX_SQL_LENGTH = 50000
    MAX_QUERY_CONTEXT_LENGTH = 16000
    MEMORY_LOG_SUMMARY_LENGTH = 240

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(plugin_logger_handler)
        self._context_manager = ContextManager()

    @classmethod
    def _summarize_memory_log_value(cls, value: str) -> str:
        """压缩并截断日志中的问题或 SQL，避免日志过长。"""
        normalized = " ".join(str(value or "").split())
        if len(normalized) <= cls.MEMORY_LOG_SUMMARY_LENGTH:
            return normalized
        return f"{normalized[:cls.MEMORY_LOG_SUMMARY_LENGTH]}..."

    @classmethod
    def _parse_query_context(cls, raw_value: Any) -> dict[str, Any]:
        """解析工作流传入的有效查询上下文，保证记忆中仅保存对象结构。"""
        raw_text = str(raw_value or "").strip()
        if not raw_text:
            return {}
        if len(raw_text) > cls.MAX_QUERY_CONTEXT_LENGTH:
            raise ValueError("提交 SQL 记忆失败：有效查询上下文内容过长")
        try:
            value = json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise ValueError("提交 SQL 记忆失败：有效查询上下文不是合法 JSON") from error
        if not isinstance(value, dict):
            raise ValueError("提交 SQL 记忆失败：有效查询上下文必须是 JSON 对象")
        return value

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        query = str(tool_parameters.get("query") or "").strip()
        sql = str(tool_parameters.get("sql") or "").strip()
        query_context = self._parse_query_context(tool_parameters.get("query_context"))
        conversation_id = str(tool_parameters.get("conversation_id") or "").strip()
        user_id = self.runtime.user_id
        runtime_session_id = self.runtime.session_id

        self.logger.info(
            "SQL_MEMORY_COMMIT_START user_id=%r conversation_id=%r runtime_session_id=%r "
            "query=%r sql=%r",
            user_id,
            conversation_id,
            runtime_session_id,
            self._summarize_memory_log_value(query),
            self._summarize_memory_log_value(sql),
        )
        self.logger.info(
            "SQL_MEMORY_CONTEXT_COMMIT conversation_id=%r context_keys=%r",
            conversation_id,
            sorted(query_context.keys()),
        )

        if not query:
            raise ValueError("提交 SQL 记忆失败：query 不能为空")
        if not sql:
            raise ValueError("提交 SQL 记忆失败：sql 不能为空")
        if len(query) > self.MAX_QUERY_LENGTH or len(sql) > self.MAX_SQL_LENGTH:
            raise ValueError("提交 SQL 记忆失败：问题或 SQL 内容过长")

        if not user_id or not conversation_id:
            self.logger.warning(
                "未提交 SQL 记忆：缺少 user_id 或 conversation_id，已避免使用共享记忆"
            )
            yield self.create_text_message(text="未提交 SQL 记忆：缺少会话标识")
            return

        committed = self._context_manager.add_conversation(
            query=query,
            sql=sql,
            user_id=user_id,
            conversation_id=conversation_id,
            metadata={
                "commit_source": "sql_execution_success",
                "query_context": query_context,
            },
        )
        if not committed:
            self.logger.error(
                "SQL_MEMORY_COMMIT_FAILED conversation_id=%r reason=context_storage_failed",
                conversation_id,
            )
            raise ValueError("提交 SQL 记忆失败：上下文存储失败")

        total_turns = self._context_manager.get_conversation_count(
            user_id=user_id,
            conversation_id=conversation_id,
        )
        self.logger.info(
            "SQL_MEMORY_COMMIT_SUCCESS conversation_id=%r total_turns=%s",
            conversation_id,
            total_turns,
        )
        yield self.create_text_message(text="SQL 记忆已提交")
