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
from tools.request_id import get_or_create_request_id

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

    def _resp(success, created, duplicate, record_id, message):
        return json.dumps({
            "success": success, "created": created, "duplicate": duplicate,
            "record_id": record_id, "message": message,
        }, ensure_ascii=False)

    # 日期一致性：相对日期已在计算端(diet_nutrition_agent)解析一次并写入请求级上下文，
    # 保存端必须复用该权威日期，禁止二次解析相对日期，避免"计算端与落库日期不一致"。
    from tools.request_date import get_resolved_date, is_ambiguous

    # 指代不明日期（那天/某天/之前那次等）：不得臆测，禁止保存。
    if is_ambiguous():
        return _resp(False, False, False, None,
                     "用餐日期不明确（无法确定具体是哪一天），请先向用户确认具体日期后再保存，禁止保存到默认日期。")

    ctx_date = get_resolved_date()
    if ctx_date:
        # 统一复用计算端解析出的权威日期（YYYY-MM-DD）
        meal_date = ctx_date

    # 第4条：idempotency_key 必须等于当前请求的 request_id。
    # 整条用户请求进入工作流时生成一次 request_id（request_id 上下文），
    # 保存重试、计算超时重试等同一请求内都会复用同一 request_id，从而不重复落库；
    # 用户补充克数/修改份量触发新请求时，request_id 不同，会生成新记录。
    key = get_or_create_request_id()
    # 若调用方显式传入 idempotency_key，仅当与请求级 request_id 一致时采用，
    # 避免出现同一请求内 key 漂移导致的重复入库。
    if idempotency_key and idempotency_key != key:
        return _resp(False, False, False, None,
                     "idempotency_key 与当前请求 request_id 不一致，已拒绝保存，请使用请求级 request_id 重试。")
    idempotency_key = key

    if meal_type not in MEAL_TYPES:
        meal_type = "snack"

    if calories < 0:
        calories = 0

    # 日期必须是合法具体日期；非法/相对日期一律拒绝，禁止默认落当天
    try:
        datetime.strptime(str(meal_date), "%Y-%m-%d")
    except (ValueError, TypeError):
        return _resp(False, False, False, None,
                     "日期格式不合法或不是具体日期（需 YYYY-MM-DD），请向用户追问具体日期后重试。")

    # 校验食物明细结构（结构非法视为参数错误，不编造数据）
    validated_items = []
    for item in food_items or []:
        if not isinstance(item, dict):
            return _resp(False, False, False, None,
                         "food_items 结构格式错误，保存失败，请检查后重试。")
        try:
            name = str(item.get("name", "未知食物"))
            cal = int(item.get("calories", 0))
        except (AttributeError, ValueError, TypeError):
            return _resp(False, False, False, None,
                         "food_items 中食物热量格式错误，保存失败，请检查后重试。")
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

    # 幂等：同 request_id 已存在则不再重复保存，返回 duplicate
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
                rid = dup.data[0].get("id") if isinstance(dup.data[0], dict) else None
                return _resp(True, False, True, rid,
                             "该请求（idempotency_key=%s）记录已存在，未重复新增。" % idempotency_key)
        except APIError:
            pass

    try:
        resp = client.table(TABLE).insert(row).execute()
    except APIError as e:
        # 并发场景下先查后写存在竞态窗口，由 DB 唯一索引兜底：
        # 重复 idempotency_key 的写入会触发 unique_violation(23505)，应转为 duplicate 而非报错。
        code = getattr(e, "code", None) or getattr(e, "status", None) or ""
        if idempotency_key and "23505" in str(code):
            return _resp(True, False, True, None,
                         "该请求（idempotency_key=%s）记录已存在（并发写入唯一约束拦截），未重复新增。" % idempotency_key)
        raise Exception(f"记录失败: {e.message}")
    except Exception as e:
        raise Exception(f"记录失败: {str(e)}")

    record_id = None
    if resp.data and isinstance(resp.data, list) and resp.data and isinstance(resp.data[0], dict):
        record_id = resp.data[0].get("id")

    type_map = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐"}
    return _resp(True, True, False, record_id,
                 "已保存 %s（%s）共 %d kcal，包含 %d 项食物。" % (
                     type_map.get(meal_type, meal_type), meal_date,
                     row["calories"], len(validated_items)))


@tool
def get_daily_intake(meal_date: str) -> str:
    """查询指定日期（YYYY-MM-DD）的全部用餐记录并汇总当日总卡路里。

    参数说明：
    - meal_date: 日期，格式 YYYY-MM-DD；也支持相对日期文本（如"今天/昨天/前天/两天前"），
      入口处会统一解析为具体 YYYY-MM-DD 并写入请求级上下文，供本请求内计算/查询/保存端复用同一日期。

    返回：当日三餐（含加餐）的记录明细与总卡路里汇总。
    """
    _get_ctx()
    client = _get_client()

    # 日期统一解析：同一个请求内，计算端(diet)、查询端(get_daily_intake)、保存端(save_meal_record)
    # 必须使用同一个解析结果。优先复用已写入请求级上下文的权威日期，避免二次解析出现分歧；
    # 相对日期在此解析一次并写入上下文；无法确定/解析失败时【不得】默认成今天，必须要求具体日期。
    from tools.date_parser import parse_relative_date, is_ambiguous_date
    from tools.request_date import get_resolved_date, set_resolved_date, set_ambiguous

    if is_ambiguous_date(meal_date):
        set_ambiguous(True)
        return "😕 用餐日期不明确（%s），无法确定具体是哪一天，请提供具体日期后重试。" % meal_date

    resolved = get_resolved_date()
    if not resolved:
        resolved = parse_relative_date(meal_date)
        if resolved is None:
            return "😕 无法解析日期「%s」为具体日期（需 YYYY-MM-DD），请提供具体日期后重试。" % meal_date
        set_resolved_date(resolved)
    meal_date = resolved

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