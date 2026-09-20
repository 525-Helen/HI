"""知识库检索与营养确定性计算工具。

提供两个能力：
- knowledge_search：从 nutrition_kb 知识库做混合语义检索，回答营养/饮食知识类问题
- diet_nutrition_agent：基于营养库对一餐做确定性热量与宏量营养计算（读取用户档案）
"""
import json
import os
import subprocess
import sys
from typing import Optional, cast

from langchain.tools import tool
from postgrest.exceptions import APIError

from storage.database.supabase_client import get_supabase_client
from coze_coding_utils.log.write_log import request_context
from coze_coding_utils.runtime_ctx.context import new_context

PROFILE_KEY = "default"
PROFILE_TABLE = "user_profiles"
KB_DATASET = "nutrition_kb"

# 用户档案 goal 值 -> 营养计算脚本 goal 值
GOAL_MAP = {"lose_fat": "lose", "fitness": "gain", "normal": "maintain"}


def _get_ctx():
    """获取请求上下文，保持链路透传。"""
    return request_context.get() or new_context(method="intake_tools")


@tool
def knowledge_search(query: str, top_k: int = 5) -> str:
    """从「nutrition_kb」营养知识库进行语义检索，回答营养知识、饮食建议、膳食指南类问题。

    当用户询问营养知识、饮食建议、膳食指南等非"记录用餐"类问题时调用。
    例如："减脂期晚餐怎么吃""蛋白质吃多少合适""哪些食物饱腹感强"。
    参数：
    - query：用户的问题或想要检索的关键词
    - top_k：返回相关条数，默认 5
    返回：JSON 字符串，包含 answer（基于知识库的答案内容或"无确切答案"提示）与 sources（引用来源列表）。
    若知识库无匹配结果，answer 为"根据现有资料，我无法提供确切答案"。
    """
    ctx = _get_ctx()
    from coze_coding_dev_sdk import Config, KnowledgeClient

    client = KnowledgeClient(config=Config(), ctx=ctx)
    try:
        resp = client.search(
            query=query,
            table_names=[KB_DATASET],
            top_k=int(top_k),
            min_score=0.5,
        )
    except Exception as e:  # noqa: BLE001
        return json.dumps({
            "answer": "知识库检索失败，请稍后再试。",
            "sources": [],
            "error": str(e),
        }, ensure_ascii=False)

    chunks = list(resp.chunks)
    if resp.code != 0 or not chunks:
        return json.dumps({
            "answer": "根据现有资料，我无法提供确切答案",
            "sources": [],
        }, ensure_ascii=False)

    answer = "\n".join(f"- {c.content}" for c in chunks[:top_k])
    sources = [
        {"doc_id": c.doc_id, "score": round(float(c.score), 4)}
        for c in chunks[:top_k]
    ]
    return json.dumps({
        "answer": answer,
        "sources": sources,
    }, ensure_ascii=False)


@tool
def diet_nutrition_agent(foods: str) -> str:
    """对一餐饮食做确定性的热量与宏量营养计算。

    当用户记录"吃了什么"（记录用餐/询问这餐热量营养时）调用本工具。
    参数：
    - foods：结构化食物明细 JSON 字符串，形如
      '[{"food":"米饭","grams":200,"confidence":0.95},{"food":"鸡胸肉","grams":150,"confidence":0.9}]'
      其中 grams 为该食物估算克数，confidence 为识别置信度(0~1，默认1)。请把"1个鸡蛋"等折算为约 50g。
    函数会读取用户已保存的身体档案（身高/体重/年龄/性别/活动水平/目标）作为计算口径；
    若未保存档案则使用默认值（30岁/男/170cm/65kg/light/maintain）。
    返回：JSON 字符串，含本餐热量(calories)、宏量(protein/carb/fat)、目标(target_*)、
    剩余热量(remaining_calories)、完成度(pct_consumed)、安全预警(risk_flags)与逐项明细(items)。
    """
    _get_ctx()
    client = get_supabase_client()

    profile = _read_profile(client)

    # 解析 foods
    try:
        items = json.loads(foods)
        if not isinstance(items, list):
            return json.dumps({"status": "error", "message": "foods 参数必须是 JSON 数组"}, ensure_ascii=False)
        for it in items:
            it.setdefault("confidence", 1.0)
    except Exception as e:  # noqa: BLE001
        return json.dumps({"status": "error", "message": f"foods 参数解析失败: {e}"}, ensure_ascii=False)

    script = os.path.join(os.getenv("COZE_WORKSPACE_PATH", "/workspace/projects"), "src/tools/nutrition_calc.py")
    cmd = [
        sys.executable, script,
        "--foods", json.dumps(items, ensure_ascii=False),
        "--age", str(profile.get("age", 30)),
        "--gender", str(profile.get("gender", "male")),
        "--height", str(profile.get("height_cm", 170)),
        "--weight", str(profile.get("weight_kg", 65)),
        "--activity", str(profile.get("activity_level", "light")),
        "--goal", GOAL_MAP.get(str(profile.get("goal", "normal")), "maintain"),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = result.stdout.strip()
        if not out:
            return json.dumps({"status": "error", "message": f"营养计算无输出: {result.stderr[:500]}"}, ensure_ascii=False)
        # 兼容脚本可能多行输出：取最后一个 JSON 行
        trial = out
        if result.returncode != 0 and not trial.startswith("{"):
            return json.dumps({"status": "error", "message": trial[:500]}, ensure_ascii=False)
        return trial[:4000]
    except Exception as e:  # noqa: BLE001
        return json.dumps({"status": "error", "message": f"营养计算执行失败: {e}"}, ensure_ascii=False)


def _read_profile(client) -> dict:
    """读取用户档案，未保存时返回空 dict（由调用方用默认值兜底）。"""
    try:
        response = (
            client.table(PROFILE_TABLE)
            .select("gender, age, height_cm, weight_kg, activity_level, goal")
            .eq("user_key", PROFILE_KEY)
            .maybe_single()
            .execute()
        )
    except APIError:
        return {}
    except Exception:  # noqa: BLE001
        return {}
    return cast(dict, response.data) if response is not None and response.data else {}