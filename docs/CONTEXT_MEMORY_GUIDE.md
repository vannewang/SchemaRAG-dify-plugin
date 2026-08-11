# Text2SQL 会话记忆使用指南

## 概述

SchemaRAG 的 SQL 记忆采用“两阶段”流程：先读取当前 Dify 会话中已经成功执行的 SQL，再只把通过外部 SQL 合法性校验且执行成功的 SQL 提交到记忆。

这个设计避免生成失败、校验失败或执行异常的 SQL 影响后续追问。

## 核心规则

- 记忆键由 `runtime.user_id + conversation_id + text2sql` 组成。同一 API 固定用户 ID 下，不同 Dify `conversation_id` 不共享记忆。
- `read_sql_memory` 只读取已提交的成功 SQL；缺少用户 ID 或 `conversation_id` 时返回空历史，不会回退到共享记忆。
- `commit_sql_memory` 只应连接到 SQL 成功分支。不要在 Text2SQL 生成完成、SQL 校验失败或 SQL 执行异常后提交。
- `query_context` 必须是 JSON 对象字符串。它保存当前轮已解析、已继承的业务对象和筛选条件，供后续追问使用。
- 当前实现使用内存存储，默认清理 24 小时未访问的上下文；记忆窗口默认返回最近 3 轮，最大 10 轮。

## 工具说明

### 读取 SQL 记忆

工具名：`read_sql_memory`

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `conversation_id` | 是 | 绑定 Dify `sys.conversation_id` |
| `memory_window_size` | 否 | 返回最近成功 SQL 的轮数，范围 1-10，默认 3 |

输出为 JSON 字符串，包含：

```json
{
  "conversation_id": "...",
  "history_turns": 2,
  "history": [
    {
      "query": "近一周的告警趋势",
      "sql": "SELECT ...",
      "query_context": {}
    }
  ],
  "latest_context": {}
}
```

`history` 用于意图解析或条件继承，`latest_context` 适合快速读取上一轮有效条件。SQL 以摘要形式返回，工作流应优先使用保存的结构化 `query_context`，而不是依赖 SQL 文本猜测条件。

### 提交 SQL 记忆

工具名：`commit_sql_memory`

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `query` | 是 | 原始用户问题，通常绑定 `sys.query` |
| `sql` | 是 | 已通过校验并成功执行的 SQL |
| `conversation_id` | 是 | 绑定 Dify `sys.conversation_id` |
| `query_context` | 否 | 本轮有效查询上下文 JSON 字符串 |

提交成功后，日志会记录会话标识与当前记忆轮数。问题和 SQL 日志仅保留截断摘要，生产环境仍应按日志管理要求保护访问权限。

## 推荐工作流

```text
开始
  ↓
读取 SQL 记忆
  ↓
查询上下文解析 / 意图解析
  ↓
有效查询上下文构建
  ↓
Text2SQL
  ↓
SQL 合法性校验
  ↓
SQL 是否安全
  ├─ 否 -> 拦截回复
  └─ 是
      ↓
    SQL 执行器
      ↓
    SQL 执行结果是否正常
      ├─ 否 -> SQL 异常处理
      └─ 是
          ↓
        提交 SQL 记忆
          ↓
        数据总结 / 页面链接 / 图表
```

### 节点绑定建议

| 节点 | 参数 | 建议绑定 |
| --- | --- | --- |
| 读取 SQL 记忆 | `conversation_id` | `sys.conversation_id` |
| Text2SQL | `content` | `sys.query` |
| Text2SQL | `conversation_id` | `sys.conversation_id` |
| Text2SQL | `query_context` | 有效查询上下文构建节点输出的 JSON 字符串 |
| 提交 SQL 记忆 | `query` | `sys.query` |
| 提交 SQL 记忆 | `sql` | SQL 安全校验后的安全 SQL |
| 提交 SQL 记忆 | `conversation_id` | `sys.conversation_id` |
| 提交 SQL 记忆 | `query_context` | 有效查询上下文构建节点输出的 JSON 字符串 |

若工作流已经使用“读取 SQL 记忆 -> 查询上下文解析”构建了完整 `query_context`，Text2SQL 的 `memory_enabled` 可按需要开启或关闭：开启时会额外把最近成功 SQL 注入 Text2SQL 提示词；关闭时仅依赖工作流传入的结构化上下文，提示词更短、行为更确定。

## 查询上下文

`query_context` 应由工作流代码节点或结构化输出节点生成，例如：

```json
{
  "schema_version": "1.0",
  "intent_type": "data_query",
  "subject": "alarm",
  "effective_time": {
    "has_time_filter": true,
    "start_ts": "2026-08-03 00:00:00",
    "end_ts": "2026-08-10 00:00:00",
    "source": "history"
  },
  "entities": {
    "algorithm_id": "101",
    "algorithm_name": "未带安全帽"
  }
}
```

Text2SQL 将此上下文作为高优先级条件：非空的有效条件需要应用到 SQL；只有用户本轮明确替换或清除条件时才可覆盖。不要传入普通文本、Markdown 或不完整 JSON。

## 使用场景

### 连续筛选

```text
第一轮：近一周的告警趋势
第二轮：这些告警都是啥算法的？
第三轮：未带安全帽有多少条，分别是什么时候的？
```

第一轮成功执行后保存时间范围；第二轮继承时间范围并查询算法；第三轮继承时间范围，同时增加算法条件。

### 新主题

开始完全独立的话题时，优先使用新的 Dify 会话。新的 `conversation_id` 会自然隔离 SQL 记忆，不会读取原会话的历史。

## 日志排查

可在 Dify `plugin_daemon` 日志中检索：

| 日志标记 | 含义 |
| --- | --- |
| `SQL_MEMORY_CONTEXT_READ_START` | 开始读取当前会话记忆 |
| `SQL_MEMORY_CONTEXT_READ_SUCCESS` | 已读取历史轮数和最近上下文状态 |
| `SQL_MEMORY_READ_RESULT` | Text2SQL 内部读取记忆的结果 |
| `SQL_MEMORY_PROMPT_INJECTED` | 最近成功 SQL 已注入 Text2SQL 提示词 |
| `SQL_MEMORY_COMMIT_START` | 成功分支开始提交记忆 |
| `SQL_MEMORY_COMMIT_SUCCESS` | 提交完成，包含当前记忆轮数 |

排查时核对同一请求中的 `conversation_id` 是否一致；`runtime_session_id` 仅用于日志辅助观察，不能替代 Dify `conversation_id` 作为记忆隔离键。

## 测试

运行上下文管理测试：

```powershell
$env:PYTHONIOENCODING='utf-8'
python test/test_context_manager.py
```

当前测试覆盖基本上下文操作、多用户隔离、固定用户 ID 下不同 Dify 会话隔离、记忆窗口和模型序列化。

## 常见问题

### 为什么没有读取到历史？

- 确认当前请求已携带非空的 `sys.conversation_id`；
- 确认前一轮 SQL 通过校验并走到了“提交 SQL 记忆”成功节点；
- 确认读取和提交节点绑定的是同一个 `conversation_id`；
- 检查 `SQL_MEMORY_CONTEXT_READ_SUCCESS` 日志中的 `history_turns`。

### 为什么追问没有继承时间或实体条件？

- 优先检查提交时保存的 `query_context` 是否为完整 JSON；
- 检查查询上下文解析节点是否将 `latest_context` 或 `history` 作为输入；
- 不要仅依赖 SQL 文本摘要解析条件。

### 为什么 SQL 没有进入记忆？

- SQL 校验失败、执行异常或未进入成功分支时，设计上不会提交记忆；
- 缺少用户 ID 或 `conversation_id` 时，提交节点会跳过写入；
- 确认提交节点使用的是校验后的 SQL，而不是空变量。
