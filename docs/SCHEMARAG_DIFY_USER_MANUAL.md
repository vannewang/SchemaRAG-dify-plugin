# SchemaRAG Dify 插件使用手册

本文档说明如何将 SchemaRAG 插件从本地 `.difypkg` 安装到 Dify，并完成 API 授权、Schema 知识库生成、Text2SQL 工作流配置、SQL 执行和结果总结/图表生成。

适用场景：

- 自托管 Dify 环境；
- 使用本地打包的 `schemarag-plugin-0.1.6.2.difypkg`；
- 使用 SchemaRAG 为数据库生成 schema 知识库；
- 在 Dify 工作流中实现自然语言问数、SQL 生成、SQL 执行、结果总结和可视化。

## 1. 前置条件

### Dify 环境

需要已有可访问的 Dify 服务，并确认以下服务正常：

- `api`
- `worker`
- `plugin_daemon`
- `nginx`
- 向量库，例如 `weaviate`
- `sandbox`

如果使用 Docker Compose 部署，可在 Dify 的 `docker` 目录下检查服务：

```powershell
cd D:\opend-project\dify\docker
docker compose ps
```

### 插件包

本地插件包示例路径：

```text
D:\opend-project\SchemaRAG-dify-plugin_wxp\schemarag-plugin-0.1.6.2.difypkg
```

如需重新打包，可在插件源码目录执行 `打包命令.md` 中的命令。

注意：该命令生成的是普通本地包，不包含 Dify 官方签名。

### 数据库账号

建议使用只读账号，至少需要读取数据库元数据和业务表结构的权限。

推荐权限原则：

- 只授予目标库或目标 schema 的读取权限；
- 不使用生产库高权限账号；
- 不使用可写账号执行问数流程；
- SQL 执行器连接账号建议限制为只读。

## 2. 关闭插件签名校验

如果使用本地普通 `.difypkg`，Dify 开启插件签名校验时会安装失败。

常见错误：

```text
PluginDaemonBadRequestError: plugin verification has been enabled, and the plugin you want to install has a bad signature
```

自托管测试环境可在 Dify Docker 配置中关闭签名校验。

在 `D:\opend-project\dify\docker\.env` 中添加或修改：

```env
FORCE_VERIFYING_SIGNATURE=false
ENFORCE_LANGGENIUS_PLUGIN_SIGNATURES=false
```

修改后重启 Dify：

```powershell
cd D:\opend-project\dify\docker
docker compose down
docker compose up -d
```

生产环境建议保持签名校验开启，只安装官方签名包或通过正式插件发布链路安装。

## 3. 上传并安装插件

1. 登录 Dify 控制台。
2. 进入插件管理页面。
3. 选择从本地上传插件包。
4. 上传：

```text
schemarag-plugin-0.1.6.2.difypkg
```

5. 安装成功后，在工具供应商或内置工具列表中应能看到：

```text
joto / schemarag
```

如果安装失败，优先检查：

- 是否关闭 `FORCE_VERIFYING_SIGNATURE`；
- 是否重启了 `plugin_daemon`；
- `.difypkg` 是否是最新打包文件；
- Dify 页面是否仍缓存旧插件状态。

## 4. 配置插件 API 授权

进入 Dify 工作流或工具供应商配置页面，找到 SchemaRAG 插件，点击 API 授权配置。

常见配置项如下。

| 配置项 | 说明 | 示例 |
| --- | --- | --- |
| Dify API URI | Dify API 地址，需要以 `/v1` 结尾 | `http://192.168.1.239:8082/v1` |
| Dify Dataset API Key | Dify 知识库 API Key | `dataset-xxxx` |
| Database Type | 数据库类型 | `postgresql` / `mysql` / `dameng` / `doris` |
| Database Host | 数据库地址 | `192.168.1.10` |
| Database Port | 数据库端口 | `5432` / `3306` / `5236` |
| Database User | 数据库用户名 | `readonly_user` |
| Database Password | 数据库密码 | `******` |
| Database Name | 数据库名 | `aicloud_inspect` |
| Database Schema | schema 名，可选 | `public` / `aicloud_inspect` |
| Tables Name | 指定表名，可选，多个表用英文逗号分隔 | `alarm_record,algorithm_info` |

### API URI 填写建议

如果插件运行在 Dify Docker 网络内部，但它调用的是 Dify 暴露出来的 HTTP 地址，通常可以填宿主机或内网访问地址：

```text
http://192.168.1.239:8082/v1
```

不要填控制台页面地址的 `/console/api`，知识库 API 应使用 `/v1`。

### Dataset API Key 获取方式

在 Dify 控制台中创建或查看知识库 API Key，通常格式类似：

```text
dataset-xxxxxxxx
```

注意：Dataset API Key 绑定工作区。必须确认该 Key 属于当前正在使用的 Dify workspace，否则知识库可能创建到另一个工作区，当前页面看不到。

## 5. 保存授权并生成 Schema 知识库

SchemaRAG 当前版本的一个重要行为是：

保存 API 授权配置时，不只是保存凭据，还会自动构建 Schema 知识库。

保存时插件会执行：

1. 校验 Dify API 配置；
2. 校验数据库连接；
3. 读取数据库表结构；
4. 生成 schema 文本；
5. 上传 schema 文本到 Dify 知识库。

日志中看到类似内容表示上传成功：

```text
POST /v1/datasets/{dataset_id}/document/create_by_text HTTP/1.1" 200
Start process document: {document_id}
Processed dataset: {dataset_id}
Task ... succeeded
```

其中 `{dataset_id}` 就是实际写入的知识库 ID。

## 6. 知识库命名和复用规则

SchemaRAG 默认根据数据库名和 schema 名生成知识库名称。

规则如下：

```python
schema_suffix = f"_{db_schema}" if db_schema else ""
dataset_name = f"{db_name}{schema_suffix}_schema"
```

示例：

| Database Name | Database Schema | 生成的知识库名 |
| --- | --- | --- |
| `aicloud_inspect` | 空 | `aicloud_inspect_schema` |
| `aicloud_inspect` | `public` | `aicloud_inspect_public_schema` |
| `aicloud_inspect` | `demo` | `aicloud_inspect_demo_schema` |

插件上传前会先查找同名知识库：

- 如果找到同名知识库，会复用已有知识库；
- 如果找不到，才创建新知识库；
- 最后向该知识库写入 schema 文档。

注意：如果多个数据库连接的 `db_name` 都叫 `aicloud_inspect`，且 `db_schema` 也相同或为空，会复用同一个知识库，可能导致 schema 混淆。

临时规避方式：

- 为不同环境填写不同 `db_schema`；
- 或者分别维护不同知识库，并手动确认 Text2SQL 节点使用正确的 `dataset_id`；
- 后续建议插件增加 `dataset_name` 或“知识库别名”配置项。

## 7. 获取 Schema 知识库 ID

保存授权后，进入 Dify 知识库列表，查找名称类似：

```text
aicloud_inspect_schema
aicloud_inspect_public_schema
```

打开知识库页面后，从 URL 中获取知识库 ID。

也可以从 Dify 日志中确认：

```text
/v1/datasets/b247c284-2abf-4879-9b26-86e062bb01b2/document/create_by_text
```

这里的：

```text
b247c284-2abf-4879-9b26-86e062bb01b2
```

就是 schema 知识库 ID。

## 8. 在工作流中配置 Text2SQL

在 Dify 工作流中添加或打开 SchemaRAG 的 `Text to SQL` 工具节点。

核心配置如下。

| 参数 | 是否必填 | 说明 |
| --- | --- | --- |
| 知识库 ID | 是 | 填写上一步生成的 schema 知识库 ID |
| 问题 | 是 | 通常绑定用户输入，例如 `sys.query` |
| LLM Model | 是 | 用于生成 SQL 的模型 |
| SQL 方言 | 是 | 根据数据库选择，例如 `postgresql`、`mysql`、`dameng` |
| Top K Results | 否 | 从知识库检索 schema 片段数量，建议 5-10 |
| Retrieval Method | 否 | 建议先用 `semantic_search` 或 `hybrid_search` |
| 自定义指令 | 否 | 用于约束 SQL 生成规则 |
| 示例知识库 ID | 否 | 放 SQL 示例或问法示例，初期可留空 |
| Enable Memory | 否 | 多轮问数时可开启 |
| Reset Memory | 否 | 需要清空上下文时设置为 `true` |

重点说明：

- Text2SQL 节点里的“知识库 ID”是运行时真正用于 schema 检索的知识库。
- API 授权配置生成的知识库 ID 不会自动回填到 Text2SQL 节点。
- 如果两个 ID 不一致，Text2SQL 会检索节点里配置的旧知识库。

示例：

```text
知识库 ID: b247c284-2abf-4879-9b26-86e062bb01b2
问题: {{#sys.query#}}
SQL 方言: postgresql
Top K Results: 5
Retrieval Method: semantic_search
```

## 9. 配置 SQL 执行器

`SQL Executer` 用于执行 Text2SQL 生成的 SQL，并返回 JSON 或 Markdown 结果。

核心参数：

| 参数 | 说明 |
| --- | --- |
| SQL Query | 绑定 Text2SQL 输出的 SQL |
| Output Format | 建议使用 `json`，便于后续总结和图表处理 |
| Max Line | 返回最大行数，建议设置，例如 `100` 或 `500` |

建议流程中在 Text2SQL 和 SQL Executer 之间增加 SQL 安全校验节点，避免模型生成危险 SQL 后直接执行。

推荐链路：

```text
开始
  ↓
Text2SQL
  ↓
SQL 安全校验代码节点
  ↓
SQL 是否安全条件判断
  ├─ 安全 -> SQL Executer
  └─ 不安全 -> 拦截回复
```

建议安全策略：

- 仅允许 `SELECT` / `WITH ... SELECT`；
- 禁止 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`TRUNCATE`、`ALTER`；
- 禁止多语句；
- 禁止危险函数或系统表访问；
- 对无显式 `LIMIT` 的查询追加默认行数限制；
- 根据业务需要限制最大 `LIMIT`。

## 10. 结果总结与图表生成

SQL 执行成功后，可接入：

```text
SQL Executer
  ↓
Data Summary
  ↓
图表数据预处理代码节点
  ↓
判断是否可画图
  ├─ 可画图 -> LLM Plot
  └─ 不可画图 -> 只返回总结
```

### Data Summary

用于根据查询问题和 SQL 结果生成业务摘要。

建议绑定：

- `data_content`: SQL 执行结果；
- `query`: 用户原始问题；
- `custom_rules`: 业务总结规则；
- `user_prompt`: 自定义总结模板。

可使用的输出结构示例：

```text
查询理解：
SQL：
结果摘要：
关键发现：
图表：
注意事项：
```

### LLM Plot

用于根据用户问题、SQL 和 JSON 数据生成图表。

建议先通过代码节点把 SQL 结果预处理成稳定结构，例如：

```json
[
  {"category": "算法A", "value": 20},
  {"category": "算法B", "value": 15}
]
```

图表生成成功率更高的条件：

- 数据行数适中；
- 至少有一个类别字段和一个数值字段；
- 字段名稳定；
- 数据不是纯文本列表；
- SQL 结果不是空数组。

## 11. 推荐测试用例

安装和配置完成后，建议按以下顺序测试。

### Schema 构建测试

保存 API 授权配置后检查：

- Dify 页面无报错；
- 日志中出现 `create_by_text 200`；
- worker 日志显示索引任务 `succeeded`；
- 知识库列表能看到对应的 `数据库名_schema`。

### Text2SQL 测试

问题示例：

```text
查询最近 10 条告警记录
```

预期：

- 能检索到相关表结构；
- 能生成 SELECT SQL；
- SQL 方言符合当前数据库；
- 不出现无关表名。

### Top N 查询测试

问题示例：

```text
我要查询告警前20位的算法
```

预期：

- SQL 中体现排序；
- SQL 中体现 `LIMIT 20` 或等价分页语法；
- SQL 执行器返回不超过 20 行。

### 安全拦截测试

问题示例：

```text
删除所有告警记录
```

预期：

- SQL 安全校验节点拦截；
- 不进入 SQL Executer；
- 返回安全提示。

### 图表测试

问题示例：

```text
统计各算法的告警数量并画图
```

预期：

- SQL 返回类别和数值；
- 预处理节点生成 `category/value` 结构；
- 可画图判断为是；
- LLM Plot 生成图表。

## 12. 常见问题

### 上传插件时报 bad signature

原因：本地 `.difypkg` 没有官方签名，但 Dify 开启了插件签名校验。

处理：

```env
FORCE_VERIFYING_SIGNATURE=false
ENFORCE_LANGGENIUS_PLUGIN_SIGNATURES=false
```

然后重启 Dify。

### 保存 API 授权后页面没报错，但看不到知识库

先看日志是否出现：

```text
POST /v1/datasets/{dataset_id}/document/create_by_text HTTP/1.1" 200
Task ... succeeded
```

如果有，说明写入成功。再检查：

- Dataset API Key 是否属于当前 workspace；
- Dify API URI 是否指向当前 Dify 实例；
- 知识库是否被复用到已有同名知识库；
- 是否在知识库列表中搜索了 `数据库名_schema`；
- 是否只看了工作流节点，而没有去知识库页面找。

### Text2SQL 生成的 SQL 不使用新知识库

原因：Text2SQL 节点中的“知识库 ID”没有改成新生成的 schema 知识库 ID。

处理：

- 打开 schema 知识库页面；
- 复制 URL 中的知识库 ID；
- 填入 Text2SQL 节点的“知识库 ID”；
- 保存并重新运行工作流。

### 多个同名数据库 schema 混在一起

原因：默认知识库名称只由 `db_name` 和 `db_schema` 组成。

处理建议：

- 不同环境使用不同 schema 或不同库名；
- 手动维护不同知识库 ID；
- 后续改造插件，增加 `dataset_name` 配置项；
- 在 schema 文档中增加来源信息，例如 host、port、database、schema。

### 图表生成成功率低

处理建议：

- SQL 尽量返回结构化统计结果；
- 控制返回行数；
- 增加图表数据预处理节点；
- 统一字段为 `category`、`value`；
- 对空结果、单列文本结果直接跳过图表。

## 13. 推荐工作流结构

完整智能问数流程建议如下：

```text
开始
  ↓
Text2SQL
  ↓
SQL 安全校验
  ↓
SQL 是否安全
  ├─ 否 -> 拦截回复
  └─ 是
      ↓
    SQL Executer
      ↓
    Data Summary
      ↓
    图表数据预处理
      ↓
    是否可生成图表
      ├─ 是 -> LLM Plot -> 最终回复
      └─ 否 -> 最终回复
```

如果只是验证基础链路，可先使用最小流程：

```text
开始 -> Text2SQL -> SQL 安全校验 -> SQL Executer -> 最终回复
```

## 14. 生产使用建议

生产环境建议：

- 恢复插件签名校验；
- 使用官方签名包或正式发布链路；
- 数据库账号使用只读权限；
- SQL 执行前必须加安全校验；
- 设置最大返回行数；
- 对高风险表、敏感字段做屏蔽或白名单；
- 不把数据库密码、Dataset API Key 写入日志；
- 多数据库场景下显式区分 schema 知识库；
- 重要问数结果保留 SQL、执行时间、查询人等审计信息。

## 15. 当前版本已知限制

- 保存 API 授权配置时会自动构建 schema 知识库，职责不够清晰；
- 构建完成后不会自动把 `dataset_id` 回填到 Text2SQL 节点；
- 默认知识库名称可能在多环境同名数据库下冲突；
- 本地打包 `.difypkg` 不包含官方签名；
- 图表生成依赖 SQL 返回数据结构，非统计类结果成功率较低；
- 示例知识库 ID 需要用户自行维护。
