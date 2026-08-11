from collections.abc import Generator
from typing import Any, Tuple, Union, List, Dict, Optional
import sys
import os
import json
import logging
from prompt import text2sql_prompt
from service.knowledge_service import KnowledgeService
from service.context import ContextManager
from service.cache import CacheManager, normalize_query, create_cache_key_from_dict, CacheConfig
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
from dify_plugin.entities.model.message import SystemPromptMessage, UserPromptMessage
from tools.parameter_validator import validate_and_extract_text2sql_parameters

# 导入 logging 和自定义处理器
from dify_plugin.config.logger_format import plugin_logger_handler

# 添加项目根目录到Python路径，以便导入service模块
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class Text2SQLTool(Tool):
    # 类级别的服务实例缓存
    _knowledge_service_cache = {}
    # 缓存大小限制，防止内存泄漏
    _cache_max_size = 10

    # 性能和配置常量
    DEFAULT_TOP_K = 5
    DEFAULT_DIALECT = "mysql"
    DEFAULT_RETRIEVAL_MODEL = "semantic_search"
    MAX_CONTENT_LENGTH = 10000  # 最大输入内容长度
    DEFAULT_MEMORY_WINDOW = 3   # 默认记忆窗口大小
    MEMORY_LOG_SUMMARY_LENGTH = 240
    MAX_QUERY_CONTEXT_LENGTH = 16000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_uri = self.runtime.credentials.get("api_uri")
        self.dataset_api_key = self.runtime.credentials.get("dataset_api_key")
        self._knowledge_service = None
        self._config_validated = False
        self.logger = logging.getLogger(__name__)
        self.logger.addHandler(plugin_logger_handler)
        
        # 初始化上下文管理器
        self._context_manager = ContextManager()
        
        # 获取SQL缓存管理器
        self._sql_cache = CacheManager.get_instance("sql_cache")

        # 初始化时验证配置
        self._validate_config()

    @property
    def knowledge_service(self):
        """延迟初始化的知识服务实例，使用缓存避免重复创建"""
        if self._knowledge_service is None:
            # 使用API配置作为缓存键
            cache_key = f"{self.api_uri}:{self.dataset_api_key}"

            if cache_key not in self._knowledge_service_cache:
                # 如果缓存已满，清理最旧的条目
                if len(self._knowledge_service_cache) >= self._cache_max_size:
                    # 删除第一个（最旧的）条目
                    oldest_key = next(iter(self._knowledge_service_cache))
                    del self._knowledge_service_cache[oldest_key]

                self._knowledge_service_cache[cache_key] = KnowledgeService(
                    self.api_uri, self.dataset_api_key
                )

            self._knowledge_service = self._knowledge_service_cache[cache_key]

        return self._knowledge_service

    def _validate_config(self):
        """验证API配置"""
        self._config_validated = bool(self.api_uri and self.dataset_api_key)
        if not self._config_validated:
            self.logger.warning("API配置不完整")

    @classmethod
    def clear_cache(cls):
        """清理服务缓存，释放资源"""
        cls._knowledge_service_cache.clear()

    @classmethod
    def get_cache_size(cls) -> int:
        """获取当前服务实例缓存大小"""
        return len(cls._knowledge_service_cache)
    
    @classmethod
    def get_cache_stats(cls) -> Dict[str, Any]:
        """
        获取所有缓存的统计信息
        
        返回:
            包含所有缓存统计信息的字典
        """
        return CacheConfig.get_summary()

    @classmethod
    def _summarize_memory_log_value(cls, value: Any) -> str:
        """压缩并截断日志中的问题或 SQL，避免日志过长。"""
        normalized = " ".join(str(value or "").split())
        if len(normalized) <= cls.MEMORY_LOG_SUMMARY_LENGTH:
            return normalized
        return f"{normalized[:cls.MEMORY_LOG_SUMMARY_LENGTH]}..."

    @staticmethod
    def _normalize_query_context_for_cache(query_context: str) -> str:
        """将有效查询上下文标准化后纳入缓存键，避免跨上下文复用 SQL。"""
        if not query_context:
            return ""
        try:
            parsed = json.loads(query_context)
            return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return " ".join(query_context.split())

    @staticmethod
    def _query_context_log_fields(query_context: str) -> tuple[str, str, bool, str, str]:
        """提取有效上下文中的关键字段，用于确认条件继承是否生效。"""
        try:
            context = json.loads(query_context) if query_context else {}
        except (TypeError, ValueError):
            context = {}
        if not isinstance(context, dict):
            context = {}
        time_value = context.get("effective_time")
        time_value = time_value if isinstance(time_value, dict) else {}
        return (
            str(context.get("subject") or "unknown"),
            str(time_value.get("source") or "none"),
            bool(time_value.get("has_time_filter")),
            str(time_value.get("start_ts") or ""),
            str(time_value.get("end_ts") or ""),
        )

    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        """
        Convert natural language questions to SQL queries using database schema knowledge base
        """
        # 早期配置验证
        if not self._config_validated:
            logging.error("错误: 缺少API配置信息")
            raise ValueError("API配置无效")

        try:
            # 验证和获取参数
            params_result = validate_and_extract_text2sql_parameters(
                tool_parameters,
                max_content_length=self.MAX_CONTENT_LENGTH,
                default_top_k=self.DEFAULT_TOP_K,
                default_dialect=self.DEFAULT_DIALECT,
                default_retrieval_model=self.DEFAULT_RETRIEVAL_MODEL,
                default_memory_window=self.DEFAULT_MEMORY_WINDOW
            )
            if isinstance(params_result, str):  # 错误消息
                logging.error(f"错误: {params_result}")
                raise ValueError(params_result)

            (dataset_id, llm_model, content, dialect, top_k, retrieval_model, 
             custom_prompt, example_dataset_id, memory_enabled, memory_window_size, reset_memory, cache_enabled) = params_result
            
            # 会话记忆必须使用工作流传入的真实 conversation_id，不能使用运行时临时 session_id。
            user_id = self.runtime.user_id
            conversation_id = str(tool_parameters.get("conversation_id") or "").strip()
            query_context = str(tool_parameters.get("query_context") or "").strip()
            if len(query_context) > self.MAX_QUERY_CONTEXT_LENGTH:
                raise ValueError("有效查询上下文内容过长")
            context_subject, time_source, has_time_filter, effective_start_ts, effective_end_ts = self._query_context_log_fields(query_context)
            runtime_session_id = self.runtime.session_id
            self.logger.info(
                "SQL_MEMORY_READ_START user_id=%r conversation_id=%r "
                "runtime_session_id=%r memory_enabled=%s memory_window_size=%s reset_memory=%s",
                user_id,
                conversation_id,
                runtime_session_id,
                memory_enabled,
                memory_window_size,
                reset_memory,
            )
            self.logger.info(
                "SQL_MEMORY_EFFECTIVE_CONTEXT conversation_id=%r present=%s length=%s "
                "subject=%r time_source=%r has_time_filter=%s start_ts=%r end_ts=%r",
                conversation_id,
                bool(query_context),
                len(query_context),
                context_subject,
                time_source,
                has_time_filter,
                effective_start_ts,
                effective_end_ts,
            )

            if memory_enabled and not (user_id and conversation_id):
                self.logger.warning(
                    "SQL_MEMORY_DISABLED reason=missing_identity user_id=%r conversation_id=%r",
                    user_id,
                    conversation_id,
                )
                memory_enabled = False
            elif not memory_enabled:
                self.logger.info("SQL_MEMORY_DISABLED reason=parameter_disabled")
            
            # 如果需要重置记忆
            if memory_enabled and reset_memory:
                reset_success = self._context_manager.reset_memory(
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                self.logger.info(
                    "SQL_MEMORY_RESET conversation_id=%r success=%s",
                    conversation_id,
                    reset_success,
                )

            # 步骤1: 从知识库检索相关的schema信息
            self.logger.info(
                f"从知识库 {dataset_id} 检索架构信息，查询长度: {len(content)}"
            )

            # 使用新的多知识库检索功能
            schema_info = self.knowledge_service.retrieve_schema_from_multiple_datasets(
                dataset_id, content, top_k, retrieval_model
            )

            if not schema_info or not schema_info.strip():
                self.logger.warning("未检索到相关的架构信息")
                schema_info = "未找到相关的数据库架构信息"

            # 步骤2: 检索示例信息（如果提供了示例知识库ID）
            example_info = ""
            if example_dataset_id and example_dataset_id.strip():
                self.logger.info(f"从示例知识库 {example_dataset_id} 检索示例信息")
                example_info = self.knowledge_service.retrieve_schema_from_multiple_datasets(
                    example_dataset_id, content, top_k, retrieval_model
                )
                if example_info and example_info.strip():
                    self.logger.info(f"检索到示例信息，长度: {len(example_info)}")
                else:
                    self.logger.info("未检索到相关的示例信息")

            # 步骤3: 获取对话历史（如果启用了记忆功能）
            conversation_history = []
            if memory_enabled and not reset_memory:
                conversation_history = self._context_manager.get_conversation_history(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    window_size=memory_window_size
                )
                self.logger.info(
                    "SQL_MEMORY_READ_RESULT conversation_id=%r history_turns=%s",
                    conversation_id,
                    len(conversation_history),
                )
                for index, history_item in enumerate(conversation_history, start=1):
                    self.logger.info(
                        "SQL_MEMORY_HISTORY_ITEM conversation_id=%r index=%s query=%r sql=%r",
                        conversation_id,
                        index,
                        self._summarize_memory_log_value(history_item.get("query")),
                        self._summarize_memory_log_value(history_item.get("sql")),
                    )
            elif reset_memory:
                self.logger.info("SQL_MEMORY_PROMPT_SKIPPED reason=reset_memory")
            else:
                self.logger.info("SQL_MEMORY_PROMPT_SKIPPED reason=memory_disabled")
            
            # 步骤4: 构建预定义的prompt（包含自定义提示、示例和对话历史）
            system_prompt = text2sql_prompt._build_system_prompt(
                dialect,custom_prompt
            )
            user_prompt = text2sql_prompt._build_user_prompt(
                db_schema=schema_info,
                question=content,
                example_info=example_info,
                conversation_history=conversation_history,
                query_context=query_context,
            )
            history_character_count = 0
            if conversation_history:
                history_character_count = sum(
                    len(str(item.get("query") or "")) + len(str(item.get("sql") or ""))
                    for item in conversation_history
                )
                self.logger.info(
                    "SQL_MEMORY_PROMPT_READY conversation_id=%r history_turns=%s "
                    "history_character_count=%s",
                    conversation_id,
                    len(conversation_history),
                    history_character_count,
                )
            elif memory_enabled and not reset_memory:
                self.logger.info(
                    "SQL_MEMORY_PROMPT_SKIPPED reason=empty_history conversation_id=%r",
                    conversation_id,
                )
            
            # 步骤4.5: 检查SQL缓存（如果启用缓存且未重置记忆）
            cache_key = None
            if cache_enabled and not reset_memory:
                # 生成缓存键
                cache_key = create_cache_key_from_dict(
                    "sql",
                    {
                        "dialect": dialect,
                        "query": normalize_query(content),
                        "dataset_id": dataset_id,
                        "custom_prompt": custom_prompt[:50] if custom_prompt else "",  # 只取前50字符
                        "query_context": self._normalize_query_context_for_cache(query_context),
                    }
                )
                
                # 尝试从缓存获取
                cached_sql = self._sql_cache.get(cache_key)
                if cached_sql:
                    self.logger.info("SQL缓存命中，直接返回缓存的SQL")
                    if conversation_history:
                        self.logger.info(
                            "SQL_MEMORY_NOT_APPLIED reason=sql_cache_hit conversation_id=%r "
                            "history_turns=%s",
                            conversation_id,
                            len(conversation_history),
                        )
                    yield self.create_text_message(text=cached_sql)
                    
                    return
            
            # 步骤5: 缓存未命中，调用LLM生成SQL
            self.logger.info("SQL缓存未命中，开始调用LLM生成SQL查询")
            if conversation_history:
                self.logger.info(
                    "SQL_MEMORY_PROMPT_INJECTED conversation_id=%r history_turns=%s "
                    "history_character_count=%s",
                    conversation_id,
                    len(conversation_history),
                    history_character_count,
                )

            response = self.session.model.llm.invoke(
                model_config=llm_model,
                prompt_messages=[
                    SystemPromptMessage(content=system_prompt),
                    UserPromptMessage(
                        content=user_prompt
                    ),
                ],
                stream=True,
            )

            # 优化流式响应处理，避免内存累积
            has_streamed_content = False
            total_content_length = 0
            generated_sql = ""  # 保存生成的SQL用于存储到上下文

            for chunk in response:
                if chunk.delta.message and chunk.delta.message.content:
                    sql_content = chunk.delta.message.content
                    has_streamed_content = True
                    total_content_length += len(sql_content)
                    generated_sql += sql_content

                    # 防止过长的响应
                    if total_content_length > 50000:  # 50KB限制
                        logging.warning("警告: 响应内容过长，已截断")
                        break

                    yield self.create_text_message(text=sql_content)

            # 如果没有流式响应，尝试获取完整响应
            if (
                not has_streamed_content
                and hasattr(response, "message")
                and response.message
            ):
                generated_sql = response.message.content
                yield self.create_text_message(text=generated_sql)

            self.logger.info(f"SQL生成完成，响应长度: {total_content_length}")
            
            # 步骤5.5: 缓存生成的SQL结果（如果启用缓存）
            if cache_enabled and generated_sql and cache_key:
                self._sql_cache.set(cache_key, generated_sql, ttl=7200)  # 2小时过期
                self.logger.debug(f"已缓存生成的SQL，键: {cache_key}")
            
            # SQL 是否可进入记忆由工作流执行成功分支的提交节点决定。

        except ValueError as e:
            self.logger.error(f"参数验证错误: {str(e)}")
            raise ValueError(f"参数错误: {str(e)}")
        except ConnectionError as e:
            self.logger.error(f"网络连接错误: {str(e)}")
            raise ValueError(f"网络连接错误: {str(e)}")
        except Exception as e:
            self.logger.error(f"SQL生成异常: {str(e)}")
            raise ValueError(f"SQL生成异常: {str(e)}")

