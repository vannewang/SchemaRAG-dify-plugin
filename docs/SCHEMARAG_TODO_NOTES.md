# SchemaRAG 插件待办与改进记录

本文档记录本地调试 SchemaRAG Dify 插件时发现的问题、当前行为和后续改进建议。

## 1. 插件打包与签名校验

### 当前现象

使用 `打包命令.md` 中的命令可以生成：

```text
schemarag-plugin-0.1.6.2.difypkg
```

但该方式本质是普通 zip 打包后改为 `.difypkg` 后缀，不包含 Dify 官方插件签名。

如果 Dify 开启插件签名校验，安装时会报错：

```text
PluginDaemonBadRequestError: plugin verification has been enabled, and the plugin you want to install has a bad signature
```

### 当前解决办法

自托管测试环境可在 Dify Docker 配置中关闭签名校验：

```env
FORCE_VERIFYING_SIGNATURE=false
ENFORCE_LANGGENIUS_PLUGIN_SIGNATURES=false
```

修改后需要重启 Dify 服务，至少重启 `plugin_daemon`，建议一起重启 `api`。

### 后续待办

- [ ] 研究并使用 Dify 官方 `dify-plugin plugin package` 打包链路。
- [ ] 区分“本地测试包”和“生产可安装签名包”。
- [ ] 在 README 或打包文档中明确说明普通 `.difypkg` 只适合关闭签名校验的自托管测试环境。

## 2. API 授权配置与知识库生成职责不清

### 当前行为

SchemaRAG 插件在保存 API 授权配置时，会执行 `_validate_credentials()`。

当前源码中 `_validate_credentials()` 不只是校验参数，还会调用：

```python
self._build_schema_rag(credentials)
```

因此，点击插件的 API 授权配置保存时，会同时触发：

- 校验 Dify API 配置；
- 校验数据库连接配置；
- 连接数据库读取 schema；
- 生成 schema 文本；
- 上传 schema 文本到 Dify 知识库。

### 问题

这个行为对用户不够直观。用户容易认为 API 授权配置只负责保存全局凭据，而知识库是在 Text2SQL 节点中配置或生成。

实际行为是：

- API 授权配置负责“生成或更新 schema 知识库”；
- Text2SQL 节点里的知识库 ID 负责“运行时从哪个知识库检索 schema”；
- 插件不会自动把生成的知识库 ID 回填到 Text2SQL 节点。

### 后续待办

- [ ] 将“校验凭据”和“构建 schema 知识库”拆开。
- [ ] 新增独立工具或节点，例如 `build_schema_rag`，专门负责构建 schema 知识库。
- [ ] 构建完成后返回明确的 `dataset_id`、知识库名称、文档 ID。
- [ ] 在 UI 或说明文档中提示用户将生成的 `dataset_id` 填入 Text2SQL 节点。

## 3. Text2SQL 节点中的知识库 ID 用途

### 当前行为

Text2SQL 节点中的“知识库 ID”是运行工作流时真正用于 schema 检索的知识库。

运行时逻辑大致为：

```text
用户问题 -> 根据 Text2SQL 节点配置的 dataset_id 检索 schema -> LLM 生成 SQL
```

“示例知识库 ID”是另一个用途，用于检索 SQL 示例、问法示例或业务查询样例，以提升 SQL 生成质量。

### 问题

如果 API 授权配置刚刚生成的 schema 知识库 ID 与 Text2SQL 节点中填写的知识库 ID 不一致，Text2SQL 会继续检索旧知识库。

例如日志中实际写入：

```text
b247c284-2abf-4879-9b26-86e062bb01b2
```

但 Text2SQL 节点配置为：

```text
47d90653-b5f9-4ad0-9191-07e9f5a75a44
```

则运行时会读取 `47d90653-b5f9-4ad0-9191-07e9f5a75a44`，不会自动读取新生成的 `b247c284-2abf-4879-9b26-86e062bb01b2`。

### 后续待办

- [ ] 在构建 schema 后明确输出生成或复用的 `dataset_id`。
- [ ] 在文档中说明 Text2SQL 节点的“知识库 ID”必须填写 schema 知识库 ID。
- [ ] 建议示例知识库 ID 默认为空，等 schema 查询稳定后再引入 SQL 示例库。

## 4. 知识库复用逻辑与多数据库冲突

### 当前行为

构建 schema 知识库时，插件根据数据库名和 schema 名生成知识库名称。

当前命名规则：

```python
schema_suffix = f"_{db_config.schema}" if db_config.schema else ""
dataset_name = f"{db_config.database}{schema_suffix}_schema"
```

示例：

```text
aicloud_inspect_schema
aicloud_inspect_public_schema
```

上传时会先调用 `/v1/datasets?page=1&limit=20` 查找同名知识库。

- 如果找到同名知识库，则复用已有知识库；
- 如果找不到，才创建新知识库；
- 最后向目标知识库写入 schema 文档。

### 问题

如果有多个数据库连接的 `db_name` 都叫 `aicloud_inspect`，且 `db_schema` 也相同或为空，则会生成同一个知识库名称。

这会导致：

- 不同数据库连接的 schema 混入同一个知识库；
- Text2SQL 检索时可能取到错误数据库的表结构；
- SQL 生成可能引用错误环境或错误库的字段；
- 后续维护时难以判断 schema 文档来源。

### 后续待办

- [ ] 新增插件配置项：`dataset_name` 或“知识库名称/别名”。
- [ ] 如果用户填写 `dataset_name`，优先使用该名称创建或复用知识库。
- [ ] 如果用户未填写，则使用兼容旧版本的默认命名规则。
- [ ] 可选：默认命名规则增加 host、port、schema 等信息，降低同名冲突概率。
- [ ] 可选：在 schema 文档内容中写入来源信息，例如数据库类型、host、port、database、schema、生成时间。

### 推荐命名示例

```text
opengauss-prod-aicloud-inspect-schema
opengauss-test-aicloud-inspect-schema
aicloud_inspect_192_168_1_10_5236_schema
aicloud_inspect_public_schema
```

## 5. 建议的产品化改造方向

更清晰的插件使用流程建议为：

1. 插件全局配置只保存 Dify API、Dataset API Key 和数据库连接信息。
2. 用户通过独立的“构建 Schema 知识库”工具触发构建。
3. 构建工具返回知识库名称、`dataset_id`、文档 ID 和构建状态。
4. 用户将返回的 `dataset_id` 填入 Text2SQL 节点。
5. Text2SQL 节点只负责根据指定知识库检索 schema 并生成 SQL。

这样职责更清晰，也更适合多个数据库连接、多个环境和多个业务库并存的场景。
