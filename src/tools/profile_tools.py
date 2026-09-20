"""个人身体数据与饮食计划工具。

提供三个能力：
- save_user_profile：保存/更新用户身体数据、目标、过敏原与忌口，并根据公式计算每日热量目标
- get_user_profile：获取已保存的用户资料与每日热量目标
- save_diet_plan：持久化大模型生成的个性化饮食计划
"""
import json
from datetime import date
from typing import Optional, cast

from langchain.tools import tool
from postgrest.exceptions import APIError

from storage.database.supabase_client import get_supabase_client
from coze_coding_utils.log.write_log import request_context
from coze_coding_utils.runtime_ctx.context import new_context

PROFILE_KEY = "default"
TABLE = "user_profiles"
PREF_TABLE = "user_preference"

GENDER_MULT = {"male": 5, "female": -161}

# 活动水平修正系数（对应久坐/轻度/中度/高度）
ACTIVITY_MULT = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
}

# 目标热量调整（kcal/日）
GOAL_ADJUST = {
    "lose_fat": -400,   # 减脂：适当热量缺口
    "fitness": 150,     # 健身增肌：热量盈余
    "normal": 0,        # 平稳维持
}


def _get_ctx():
    """获取请求上下文，保持链路透传。"""
    return request_context.get() or new_context(method="profile_tools")


def _get_client():
    """获取 Supabase 客户端（服务端操作，service_role_key 绕过 RLS）。"""
    return get_supabase_client()


def _compute_daily_target(gender: str, age: int, height_cm: int, weight_kg: float,
                          activity_level: str, goal: str) -> int:
    """基于 Mifflin-St Jeor 公式计算每日热量目标（kcal）。

    BMR(男) = 10*kg + 6.25*cm - 5*age + 5
    BMR(女) = 10*kg + 6.25*cm - 5*age - 161
    TDEE = BMR * 活动系数，再按目标叠加能量调整。
    """
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    bmr = base + GENDER_MULT.get(gender, 5)
    tdee = bmr * ACTIVITY_MULT.get(activity_level, 1.2)
    target = tdee + GOAL_ADJUST.get(goal, 0)
    return int(round(target))


def _parse_tags(value) -> list:
    """将过敏原/忌口参数规范化为字符串数组。

    兼容 JSON 数组字符串（如 ["虾","海鲜"]）、逗号分隔字符串（如 "虾,海鲜"）、单个字符串。
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, dict):
        return []
    s = str(value).strip()
    if not s:
        return []
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
    except Exception:  # noqa: BLE001
        pass
    # 逗号 / 顿号 / 空格分隔
    import re
    parts = re.split(r"[，,、/]", s)
    return [p.strip() for p in parts if p.strip()]


def _read_existing_profile(client) -> dict:
    """读取当前已保存的身体数据，用于合并更新（单用户模式）。"""
    try:
        response = (
            client.table(TABLE)
            .select("gender, age, height_cm, weight_kg, activity_level, goal")
            .eq("user_key", PROFILE_KEY)
            .maybe_single()
            .execute()
        )
    except Exception:  # noqa: BLE001
        return {}
    return cast(dict, response.data) if response is not None and response.data else {}


def _read_preference(client) -> dict:
    """读取已保存的过敏原/忌口偏好（user_preference，单用户模式）。"""
    try:
        response = (
            client.table(PREF_TABLE)
            .select("allergens, dislikes")
            .eq("user_id", PROFILE_KEY)
            .maybe_single()
            .execute()
        )
    except Exception:  # noqa: BLE001
        return {}
    data = response.data if response is not None and response.data else {}
    allergens = data.get("allergens") or []
    dislikes = data.get("dislikes") or []
    if isinstance(allergens, str):
        try:
            allergens = json.loads(allergens)
        except Exception:  # noqa: BLE001
            allergens = []
    if isinstance(dislikes, str):
        try:
            dislikes = json.loads(dislikes)
        except Exception:  # noqa: BLE001
            dislikes = []
    return {
        "allergens": [str(x) for x in allergens] if isinstance(allergens, list) else [],
        "dislikes": [str(x) for x in dislikes] if isinstance(dislikes, list) else [],
    }


@tool
def save_user_profile(
    gender: Optional[str] = None,
    age: Optional[int] = None,
    height_cm: Optional[int] = None,
    weight_kg: Optional[float] = None,
    activity_level: Optional[str] = None,
    goal: Optional[str] = None,
    allergens: Optional[str] = None,
    dislikes: Optional[str] = None,
) -> str:
    """保存/更新用户的任意组合信息：身体数据、饮食目标、过敏原、忌口。会自动计算每日热量目标，并持久化过敏原与忌口。

    参数说明（均为可选，未提供的字段保持原值；用户声明某一项时只需传该项即可）：
    - gender: 性别，male(男) / female(女)
    - age: 年龄
    - height_cm: 身高（厘米）
    - weight_kg: 体重（公斤）
    - activity_level: 活动水平，sedentary(久坐)/light(轻度)/moderate(中度)/active(高度)
    - goal: 目标，lose_fat(减脂)/fitness(健身增肌)/normal(平稳维持)
    - allergens: 过敏原，JSON数组字符串（如 "["虾","海鲜"]"）或逗号分隔字符串；会写入 user_preference 供餐食过敏拦截
    - dislikes: 忌口/不喜欢的食物，JSON数组字符串或逗号分隔字符串；会写入 user_preference

    【重要】当用户声明过敏原、忌口或变更目标时，必须调用本工具落档；本工具会把 allergens/dislikes 持久化到 user_preference 表。
    返回：已保存的用户资料、过敏原/忌口与每日热量目标。
    """
    _get_ctx()
    client = _get_client()

    # 读取已有档案，未提供的字段保持原值（单用户模式）
    existing = _read_existing_profile(client)
    if gender is None:
        gender = existing.get("gender") or "male"
    if age is None:
        age = existing.get("age") or 30
    if height_cm is None:
        height_cm = existing.get("height_cm") or 170
    if weight_kg is None:
        weight_kg = existing.get("weight_kg") or 65.0
    if activity_level is None:
        activity_level = existing.get("activity_level") or "sedentary"
    if goal is None:
        goal = existing.get("goal") or "normal"

    # 过敏原/忌口：仅在本次显式提供时才更新；未提供则保留已有 preference 的值，避免互相覆盖
    existing_pref = _read_preference(client)
    if allergens is None:
        allergens = existing_pref.get("allergens", [])
    else:
        allergens = _parse_tags(allergens)
    if dislikes is None:
        dislikes = existing_pref.get("dislikes", [])
    else:
        dislikes = _parse_tags(dislikes)

    if gender not in GENDER_MULT:
        gender = "male"
    if activity_level not in ACTIVITY_MULT:
        activity_level = "sedentary"
    if goal not in GOAL_ADJUST:
        goal = "normal"

    # 1) 写 user_profiles（身体数据 + 目标 + 热量目标）
    target = _compute_daily_target(gender, int(age), int(height_cm), float(weight_kg), activity_level, goal)
    row = {
        "user_key": PROFILE_KEY,
        "gender": gender,
        "age": int(age),
        "height_cm": int(height_cm),
        "weight_kg": float(weight_kg),
        "activity_level": activity_level,
        "goal": goal,
        "daily_calorie_target": target,
        "updated_at": "now()",
    }
    try:
        client.table(TABLE).upsert(row, on_conflict="user_key").execute()
    except APIError as e:
        raise Exception(f"保存个人资料失败: {e.message}")
    except Exception as e:
        raise Exception(f"保存个人资料失败: {str(e)}")

    # 2) 写 user_preference（过敏原 + 忌口 + 目标）
    pref_row = {
        "user_id": PROFILE_KEY,
        "allergens": json.dumps(allergens, ensure_ascii=False) if allergens else "[]",
        "dislikes": json.dumps(dislikes, ensure_ascii=False) if dislikes else "[]",
        "goal_type": goal,
        "updated_at": "now()",
    }
    try:
        client.table(PREF_TABLE).upsert(pref_row, on_conflict="user_id").execute()
    except APIError as e:
        raise Exception(f"保存过敏原/忌口失败: {e.message}")
    except Exception as e:
        raise Exception(f"保存过敏原/忌口失败: {str(e)}")

    goal_map = {"lose_fat": "减脂", "fitness": "健身增肌", "normal": "平稳维持"}
    act_map = {"sedentary": "久坐", "light": "轻度", "moderate": "中度", "active": "高度"}
    parts = [
        f"已保存个人资料：性别{'男' if gender == 'male' else '女'}，{age}岁，"
        f"{height_cm}cm / {weight_kg}kg，活动水平【{act_map[activity_level]}】，"
        f"目标【{goal_map[goal]}】。",
        f"🎯 建议每日摄入 **{target} kcal**（根据 BMR/TDEE 与目标推算，仅供参考）。",
    ]
    if allergens:
        parts.append(f"🛡️ 已记录过敏原：{', '.join(allergens)}。后续餐食将据此触发过敏拦截。")
    if dislikes:
        parts.append(f"🚫 已记录忌口：{', '.join(dislikes)}。")
    return "\n".join(parts)


@tool
def get_user_profile() -> str:
    """获取当前用户已保存的身体数据、目标与每日热量目标，以及已存档的饮食计划。

    返回：用户资料概要，若尚未保存则提示先填写身体数据。
    """
    _get_ctx()
    client = _get_client()

    try:
        response = (
            client.table(TABLE)
            .select("gender, age, height_cm, weight_kg, activity_level, goal, daily_calorie_target, diet_plan")
            .eq("user_key", PROFILE_KEY)
            .maybe_single()
            .execute()
        )
    except APIError as e:
        raise Exception(f"查询个人资料失败: {e.message}")
    except Exception as e:
        raise Exception(f"查询个人资料失败: {str(e)}")

    if response is None:
        return "📋 尚未填写个人资料。请提供你的身高、体重、年龄、性别、日常活动水平以及目标（减脂/健身/正常），以便我为你制定饮食计划。"

    p: dict = cast(dict, response.data)
    goal_map = {"lose_fat": "减脂", "fitness": "健身增肌", "normal": "平稳维持"}
    act_map = {"sedentary": "久坐", "light": "轻度", "moderate": "中度", "active": "高度"}
    gender = p.get("gender")
    lines = [
        f"📋 个人资料：性别{'男' if gender == 'male' else '女'}，{p.get('age')}岁，"
        f"{p.get('height_cm')}cm / {p.get('weight_kg')}kg，"
        f"活动水平【{act_map.get(p.get('activity_level'), '轻度')}】",
        f"🎯 目标【{goal_map.get(p.get('goal'), '平稳维持')}】",
        f"🔥 每日热量目标：**{p.get('daily_calorie_target')} kcal**",
    ]

    # 补充过敏原/忌口（来自 user_preference）
    pref = _read_preference(client)
    if pref.get("allergens"):
        lines.append(f"🛡️ 过敏原：{'、'.join(pref['allergens'])}")
    if pref.get("dislikes"):
        lines.append(f"🚫 忌口：{'、'.join(pref['dislikes'])}")

    if p.get("diet_plan"):
        lines.append(f"\n📖 已存档饮食计划：\n{p.get('diet_plan')}")
    return "\n".join(lines)


@tool
def save_diet_plan(plan: str) -> str:
    """保存大模型为当前用户生成的个性化饮食计划（Markdown 文本），以便后续回顾。

    参数说明：
    - plan: 饮食计划的 Markdown 文本，包含三餐热量分配与食物建议等。

    返回：保存结果说明。
    """
    _get_ctx()
    client = _get_client()

    try:
        response = (
            client.table(TABLE)
            .update({"diet_plan": plan})
            .eq("user_key", PROFILE_KEY)
            .execute()
        )
    except APIError as e:
        raise Exception(f"保存饮食计划失败: {e.message}")
    except Exception as e:
        raise Exception(f"保存饮食计划失败: {str(e)}")

    if not response.data:
        return "⚠️ 尚未建立个人资料，无法保存饮食计划。请先提供身体数据与目标（save_user_profile）。"
    return "✅ 你的个性化饮食计划已保存，随时可回顾。"