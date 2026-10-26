"""验证外部环境(shim)下 external_main 能完整跑通核心链路。

模拟外部主机：不依赖 Coze 平台库，强制 src_external 的 coze_coding_utils shim 生效。
"""
import os
import sys

# 强制 EXTERNAL_MODE，并把 src_external shim 放最前
os.environ["EXTERNAL_MODE"] = "1"
os.environ["EXTERNAL_OPENAI_BASE_URL"] = "https://llmapi.paratera.com/v1"
os.environ["EXTERNAL_OPENAI_API_KEY"] = "sk-A_lNM2yYTz_K-INk1X0VnQ"
os.environ["EXTERNAL_OPENAI_MODEL"] = "DeepSeek-V4-Pro-0813"
os.environ["EXTERNAL_KNOWLEDGE_DISABLED"] = "1"

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
os.environ["COZE_WORKSPACE_PATH"] = _root
sys.path.insert(0, os.path.join(_root, "src"))
sys.path.insert(0, os.path.join(_root, "src_external"))

# 阻断真实 coze_coding_utils（若沙箱中恰好可导入），确保走 shim
import importlib
try:
    import coze_coding_utils  # noqa
    print("WARN: 检测到真实 coze_coding_utils，blockpath 测试会失真")
except ImportError:
    pass

from fastapi.testclient import TestClient
from external_main import app

client = TestClient(app)

u = "ext-shim-test"
r = client.get("/health")
print("health:", r.status_code, r.json())

# 1) 建档
r1 = client.post("/run", json={"messages": [{"role": "user", "content": "请保存我的用户档案：性别男，年龄30岁，身高178cm，体重75kg，当前目标减脂，活动水平中等，过敏与忌口为无。"}]},
                 headers={"x-user-id": u, "x-run-id": "run-a"})
print("建档 /run:", r1.status_code)
print("  回复:", r1.json()["messages"][-1]["content"][:120])

# 2) 记录一餐（触发本地 FOOD_DB 确定性计算 + Supabase 落库）
r2 = client.post("/run", json={"messages": [{"role": "user", "content": "今天午餐吃了200g米饭和150g鸡胸肉，帮我记录并计算热量"}]},
                 headers={"x-user-id": u, "x-run-id": "run-b"})
print("记录 /run:", r2.status_code)
print("  回复:", r2.json()["messages"][-1]["content"][:160])

print("\nDONE")