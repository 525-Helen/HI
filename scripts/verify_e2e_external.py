"""外部入口端到端测试：用 TestClient 驱动 external_main 完整链路。
仅验证 / 前端、/health、/run（真实外部 LLM + 用户隔离），不伪造数据。
"""
import os
os.environ.setdefault("EXTERNAL_OPENAI_BASE_URL", "https://llmapi.paratera.com/v1")
os.environ.setdefault("EXTERNAL_OPENAI_API_KEY", "sk-A_lNM2yYTz_K-INk1X0VnQ")
os.environ.setdefault("EXTERNAL_OPENAI_MODEL", "DeepSeek-V4-Pro-0813")
os.environ.setdefault("EXTERNAL_KNOWLEDGE_DISABLED", "1")

import uuid
from fastapi.testclient import TestClient
from external_main import app

client = TestClient(app)

print("== 1. 根路径 ==")
r = client.get("/")
print("root:", r.status_code, "has_ui:", "AI个性化饮食管理" in r.text)

print("\n== 2. health ==")
print("health:", client.get("/health").json())

print("\n== 3. /run 建档 ==")
uid_a = "ext-e2e-" + uuid.uuid4().hex[:8]
run_a1 = "run-" + uuid.uuid4().hex[:8]
pa = {"messages": [{"role": "user", "content": "请保存我的用户档案：性别女，年龄28岁，身高165cm，体重55kg，当前目标减脂，活动水平中等，过敏与忌口为花生、海鲜。"}]}
ra = client.post("/run", json=pa, headers={"x-user-id": uid_a, "x-run-id": run_a1}).json()
final_a = ra["messages"][-1]["content"]
print("建档 reply:", final_a[:120].replace("\n", " "))

print("\n== 4. /run 记录一餐（用户A）==")
run_a2 = "run-" + uuid.uuid4().hex[:8]
pa2 = {"messages": [{"role": "user", "content": "今天午餐吃了200g米饭和150g鸡胸肉，帮我记录并算热量"}]}
ra2 = client.post("/run", json=pa2, headers={"x-user-id": uid_a, "x-run-id": run_a2}).json()
final_a2 = ra2["messages"][-1]["content"]
print("记录 reply:", final_a2[:160].replace("\n", " "))

print("\n== 5. 用户隔离：新用户B查今日摄入 ==")
uid_b = "ext-e2e-" + uuid.uuid4().hex[:8]
run_b1 = "run-" + uuid.uuid4().hex[:8]
pb = {"messages": [{"role": "user", "content": "今天我的午餐吃了多少热量？帮我查询今日摄入"}]}
rb = client.post("/run", json=pb, headers={"x-user-id": uid_b, "x-run-id": run_b1}).json()
final_b = rb["messages"][-1]["content"]
print("B reply:", final_b[:200].replace("\n", " "))

print("\n== 6. 用户A再次查询（隔离确认）==")
run_a3 = "run-" + uuid.uuid4().hex[:8]
pa3 = {"messages": [{"role": "user", "content": "帮我查询我今天的总摄入是多少"}]}
ra3 = client.post("/run", json=pa3, headers={"x-user-id": uid_a, "x-run-id": run_a3}).json()
final_a3 = ra3["messages"][-1]["content"]
print("A reply:", final_a3[:200].replace("\n", " "))