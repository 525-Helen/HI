# 「卡卡」AI 饮食热量管理 Agent · 启动与配置说明

## 1. 目录结构
```
├── config/agent_llm_config.json   # LLM/工具/Prompt 配置（唯一配置源）
├── src/
│   ├── main.py                    # FastAPI 服务入口（GraphService）
│   ├── agents/agent.py            # create_agent 编排：工具、middleware、短期记忆
│   ├── tools/                     # 业务工具
│   │   ├── audit_log.py           # 请求级审计日志与指标统计（V6）
│   │   ├── nutrition_calc.py      # 营养确定性计算（份量三级+S0硬拦截）
│   │   ├── intake_tools.py        # knowledge_search / diet_nutrition_agent
│   │   ├── meal_tools.py          # save_meal_record / get_daily_intake
│   │   ├── profile_tools.py       # save/get/delete_user_profile、save_diet_plan
│   │   ├── date_parser.py         # 相对日期解析
│   │   └── request_id.py / request_date.py  # 请求级上下文
│   ├── storage/                   # Postgres(Supabase)/Memory/S3 封装
│   └── graphs/                    # （本仓库为单 Agent，无独立图文件）
├── assets/                        # 测试集 xlsx、前端 demo
├── docs/                          # 测试报告、本说明
├── scripts/                       # local_run/http_run/setup/pack 等
├── pyproject.toml / uv.lock       # 依赖（uv 管理）
└── .coze                          # 平台构建/运行配置
```

## 2. 前置环境变量
| 变量 | 说明 |
|---|---|
| `COZE_WORKSPACE_PATH` | 项目根目录（默认 `/workspace/projects`），已加入 PYTHONPATH |
| `COZE_INTEGRATION_MODEL_BASE_URL` / `COZE_WORKLOAD_IDENTITY_API_KEY` | 模型网关地址与凭据 |
| `DATABASE_URL` / `PGDATABASE_URL` | Postgres(Supabase) 连接串（记忆/档案/餐食/审计依赖） |
| `COZE_AUDIT_LOG_FILE`（可选） | 覆盖审计日志文件路径，默认随根日志 `/app/work/logs/bypass/app.log` |

## 3. 安装与运行（uv，禁止 pip）
```bash
uv sync                 # 按 uv.lock 安装
bash scripts/setup.sh   # 构建/安装依赖
bash scripts/http_run.sh   # 启动 HTTP 服务（OpenAI 兼容 /run /stream_run）
bash scripts/local_run.sh -m flow    # 本地 flow 运行
bash scripts/local_run.sh -m node -n <node>  # 运行单个节点
```
> 端口规范：系统服务使用 9000，其他服务端口以 `http_run.sh` 为准，禁止触碰 9000。

## 4. 配置文件示例（config/agent_llm_config.json 结构）
```jsonc
{
  "config": {                        // 必填 object
    "model": "doubao-seed-2-0-lite-260215",   // 来自技能/用户指定，禁止编造
    "temperature": 0.4,
    "top_p": 0.9,
    "max_completion_tokens": 4000,
    "timeout": 60,
    "thinking": "disabled"
  },
  "sp": "# 角色\n你是……",            // 必填非空 string（Agent System Prompt）
  "tools": [ "save_meal_record: …" ] // 必填 array（string 元素，可为 []）
}
```
- `agent.py` 读取 `config/` 下的该文件构建 `ChatOpenAI` 与 `create_agent`。
- `tools` 数组为工具描述清单；实际工具绑定在 `agent.py` 的 `tools=` 列表。

## 5. 核心运行时编排（Workflow 说明）
本 Agent 为**单 Agent（create_agent）**，无独立 LangGraph 图文件，会话链路如下：
```
用户输入
  → create_agent(model=LLM, system_prompt=sp, tools=[save_meal_record, get_daily_intake,
      save_user_profile, get_user_profile, save_diet_plan, delete_user_profile,
      knowledge_search, diet_nutrition_agent],
      middleware=[audit_tool_calls], checkpointer=PostgresSaver, state_schema=AgentState)
  → 意图分流（记录/查询/知识问答/建档）由 System Prompt 约束
  → diet_nutrition_agent 确定性计算（份量三级 + S0硬拦截 + refuse 零泄露）
  → save_meal_record 幂等保存（请求级 request_id 唯一）
  → 审计中间件落请求级日志（含工具参数/耗时/错误/返回摘要）
```
- **短期记忆**：滑动窗口保留最近 20 轮（40 条消息），checkpointer 按 `thread_id`（生产 `=ctx.run_id`，测试固定 `'123'`）持久化到 Postgres。
- **幂等**：`save_meal_record.idempotency_key` 恒等于请求级 `request_id`，同 key 重复返回 `duplicate` 且不落库，并发由唯一索引 `uq_meal_request_id` 兜底。
- **审计与指标**：见 `src/tools/audit_log.py`，`record_tool_call` 写 JSON 审计行；`compute_metrics()` 回放给出工具失败率/平均耗时/按请求聚合/save_count；Token 与调用成本标记 `not_connected`（需网关）。

## 6. 知识库（nutrition_kb）
- 为扣子平台云端数据集（Semantic 检索，`coze_coding_dev_sdk.KnowledgeClient`），非本地文件。
- 已通过 SDK 导入文档：**乳制品过敏者早餐高蛋白替代方案**（参考《中国居民膳食指南(2022)》《中国食物成分表(第6版)》），代表性 `doc_id=7696736745181822976`。
- 检索不到或来源无法支撑时，Agent 被约束如实拒答、不编造来源/数据。

## 7. 测试
- 测试集：`assets/` 下 V3/V4/V5 独立留出集（xlsx）等。
- 隔离：用 `DELETE` 清空 thread`'123'` 的 memory 表、清空 `user_preference`、`UPDATE user_profiles` 恢复中性档案（female/30/165/68/moderate/normal/2170）、`DELETE meal_records WHERE id>15`。
- 运行：通过 `test_run`（HTTP）逐条执行并核对库表落库、request_id、日期一致性。
- 结果：见 `docs/TEST_REPORT_V1_V6.md`。

## 8. 说明
- 禁止使用 `pip`（虚拟环境无 pip），依赖一律走 `uv add`/`uv sync`。
- 除用户明确要求保存到本地外，生成文件默认写 `/tmp` 后上传对象存储返回 URL。