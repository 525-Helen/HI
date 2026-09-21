"""一日三餐卡路里记录工具。

提供两个能力：
- save_meal_record：将用户某餐的卡路里摄入记录持久化到 Supabase
- get_daily_intake：查询某一天的全部用餐记录并汇总卡路里
"""
import json
from datetime import date, datetime
from typing import List, Optional, cast

from langchain.tools import tool
from postgrest.exceptions import APIError

from storage.database.supabase_client import get_supabase_client
from coze_coding_utils.log.write_log import request_context
from coze_coding_utils.runtime_ctx.context import new_context

MEAL_TYPES = ["breakfast", "lunch", "dinner", "snack"]

TABLE = "meal_records"


def _get_ctx():
    """获取请求上下文，保持链路透传。"""
    return request_context.get() or new_context(method="meal_tools")


def _get_client():
    """获取 Supabase 客户端（服务端操作，service_role_key 绕过 RLS）。"""
    return get_supabase_client()


def _nutrition_estimate(food_name: str) -> int:
    """根据常见食物名称估算单份卡路里（单位 kcal）。仅作为兜底参考，主估算由模型完成。"""
    table = {
        "米饭": 116, "馒头": 223, "面条": 110, "面包": 260, "鸡蛋": 78, "牛奶": 65,
        "酸奶": 72, "豆浆": 31, "苹果": 53, "香蕉": 93, "蔬菜": 25, "鸡胸肉": 133,
        "牛肉": 125, "猪肉": 143, "鱼": 105, "虾": 99, "沙拉": 60, "燕麦": 150,
        "粥": 46, "水果": 50, "汉堡": 300, "薯条": 320, "可乐": 140,
    }
    for key, val in table.items():
        if key in food_name:
            return val
    return 100


@tool
def save_meal_record(
    meal_type: str,
    meal_date: str,
    calories: int,
    food_items: List[dict],
    notes: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> str:
    """记录一餐的卡路里摄入并持久化（仅允许保存在 diet_nutrition_agent 明确允许落库的结果）。

    参数说明：
    - meal_type: 餐次，取值 breakfast(早餐) / lunch(午餐) / dinner(晚餐) / snack(加餐)
    - meal_date: 用餐日期，格式 YYYY-MM-DD（必须使用 diet_nutrition_agent 返回的具体日期）
    - calories: 该餐总卡路里（kcal，整数）
    - food_items: 食物明细列表，每项为 {"name": "食物名称", "calories": 单项卡路里}
    - notes: 备注（可选）
    - idempotency_key: 幂等键（可选），用于避免同一餐/同一请求重复保存。建议用 "{meal_date}_{meal_type}_{主食物}" 或来源 request_id。已有同 key 记录时会返回提示并跳过，不会二次入库。

    约束（重要）：
    - 只有在 diet_nutrition_agent 返回 needs_clarification=false 且无未处理的关键风险时才可调用；
    - 若份量仍待澄清、工具失败或存在未处理过敏等关键风险，【禁止】调用本工具。

    返回：记录结果说明。
    """
    _get_ctx()
    client = _get_client()

    if meal_type not in MEAL_TYPES:
        meal_type = "snack"

    if calories < 0:
        calories = 0

    # 校验日期格式，失败则按当天（不编造相对日期）
    try:
        datetime.strptime(meal_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        meal_date = date.today().isoformat()

    # 校验食物明细结构
    validated_items = []
    for item in food_items or []:
        try:
            name = str(item.get("name", "未知食物"))
            cal = int(item.get("calories", 0))
        except (AttributeError, ValueError, TypeError):
            continue
        validated_items.append({"name": name, "calories": cal})

    row = {
        "meal_type": meal_type,
        "meal_date": meal_date,
        "calories": int(calories),
        "food_items": validated_items if validated_items else [{"name": "其他", "calories": int(calories)}],
        "notes": notes,
    }
    if idempotency_key:
        row["request_id"] = idempotency_key

    # 幂等：同 request_id 已存在则不再重复保存
    if idempotency_key:
        try:
            dup = (
                client.table(TABLE)
                .select("request_id")
                .eq("request_id", idempotency_key)
                .limit(1)
                .execute()
            )
            if dup.data:
                return f"该请求（idempotency_key={idempotency_key}）已记录过，未重复保存。"
        except APIError:
            pass

    try:
        client.table(TABLE).insert(row).execute()
    except APIError as e:
        raise Exception(f"记录失败: {e.message}")
    except Exception as e:
        raise Exception(f"记录失败: {str(e)}")

    type_map = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐"}
    return (
        f"已记录 {type_map.get(meal_type, meal_type)}（{meal_date}）"
        f"共 {row['calories']} kcal，包含 {len(validated_items)} 项食物。"
    )


@tool
def get_daily_intake(meal_date: str) -> str:
    """查询指定日期（YYYY-MM-DD）的全部用餐记录并汇总当日总卡路里。

    参数说明：
    - meal_date: 日期，格式 YYYY-MM-DD

    返回：当日三餐（含加餐）的记录明细与总卡路里汇总。
    """
    _get_ctx()
    client = _get_client()

    try:
        datetime.strptime(meal_date, "%Y-%m-%d")
    except ValueError:
        meal_date = date.today().isoformat()

    try:
        response = (
            client.table(TABLE)
            .select("meal_type, calories, food_items, notes, created_at")
            .eq("meal_date", meal_date)
            .order("created_at")
            .execute()
        )
    except APIError as e:
        raise Exception(f"查询失败: {e.message}")
    except Exception as e:
        raise Exception(f"查询失败: {str(e)}")

    records: List[dict] = cast(List[dict], response.data or [])
    if not records:
        return f"🥗 {meal_date} 还没有任何用餐记录。"

    type_map = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐"}
    total = 0
    lines = [f"📅 {meal_date} 的用餐记录："]
    for r in records:
        meal_type = str(r.get("meal_type") or "snack")
        cal = int(r.get("calories") or 0)
        total += cal
        raw_items = r.get("food_items") or []
        items = raw_items if isinstance(raw_items, list) else []
        item_str = "、".join(
            f"{str(i.get('name', '食物'))}({int(i.get('calories', 0))}kcal)"
            for i in items
            if isinstance(i, dict)
        )
        note = f"　备注：{r.get('notes')}" if r.get("notes") else ""
        lines.append(f"- {type_map.get(meal_type, meal_type)}：{cal} kcal　[{item_str}]{note}")
    lines.append(f"\n🔥 当日总摄入：**{total} kcal**")
    return "\n".join(lines)