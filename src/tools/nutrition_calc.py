#!/usr/bin/env python3
"""确定性营养计算工具：用于"AI 饮食热量与营养管理 Agent"。

读取结构化食物明细与用户档案，计算本餐热量/宏量营养素、目标热量、
剩余额度、完成度，并叠加过敏原/低置信度/库缺失/低热量等安全预警。

份量取值遵循"精准优先、估算兜底"三级逻辑：
  L0 明确克数(grams>0)        → 直接计算，不查 PORTION_MAP
  L1 生活化描述(portion_desc)  → 命中 PORTION_MAP 映射克数，confidence=0.6，继续计算
  L2 说"不知道"(portion_state=unknown)      → needs_clarification=true, clarification_type="estimate"，引导进参照物
  L3 仍说"不知道"(portion_state=unknown_still)→ 按食物类型取默认值，confidence=0.4，附 ±20% 提示
  模糊单位(碗/盘/块等，无克数/无描述/无状态)  → needs_clarification=true, clarification_type="grams"，强制问克数

独立命令行工具，输出 JSON 到 stdout，供智能体调用后读取结果。
"""
import argparse
import json
import sys

# 内置营养库：每 100g 的热量与宏量营养素（热量kcal/蛋白g/碳水g/脂肪g）
FOOD_DB = {
    "米饭": {"热量_kcal": 116, "蛋白_g": 2.6, "碳水_g": 25.9, "脂肪_g": 0.3},
    "白米饭": {"热量_kcal": 116, "蛋白_g": 2.6, "碳水_g": 25.9, "脂肪_g": 0.3},
    "馒头": {"热量_kcal": 223, "蛋白_g": 7.0, "碳水_g": 47.0, "脂肪_g": 1.1},
    "面条": {"热量_kcal": 110, "蛋白_g": 3.2, "碳水_g": 22.5, "脂肪_g": 0.2},
    "意大利面": {"热量_kcal": 380, "蛋白_g": 13.0, "碳水_g": 75.0, "脂肪_g": 1.5},
    "鸡胸肉": {"热量_kcal": 165, "蛋白_g": 31.0, "碳水_g": 0.0, "脂肪_g": 3.6},
    "鸡腿肉": {"热量_kcal": 180, "蛋白_g": 20.0, "碳水_g": 0.0, "脂肪_g": 10.0},
    "鸡蛋": {"热量_kcal": 144, "蛋白_g": 13.3, "碳水_g": 2.8, "脂肪_g": 8.8},
    "鸡蛋白": {"热量_kcal": 52, "蛋白_g": 11.0, "碳水_g": 0.7, "脂肪_g": 0.2},
    "牛肉": {"热量_kcal": 125, "蛋白_g": 20.2, "碳水_g": 1.2, "脂肪_g": 4.2},
    "瘦猪肉": {"热量_kcal": 143, "蛋白_g": 20.3, "碳水_g": 1.5, "脂肪_g": 6.2},
    "三文鱼": {"热量_kcal": 208, "蛋白_g": 20.4, "碳水_g": 0.0, "脂肪_g": 13.4},
    "虾": {"热量_kcal": 93, "蛋白_g": 18.6, "碳水_g": 2.8, "脂肪_g": 0.8},
    "螃蟹": {"热量_kcal": 97, "蛋白_g": 17.5, "碳水_g": 2.2, "脂肪_g": 2.6},
    "豆腐": {"热量_kcal": 84, "蛋白_g": 8.1, "碳水_g": 4.2, "脂肪_g": 3.7},
    "豆浆": {"热量_kcal": 31, "蛋白_g": 3.0, "碳水_g": 1.2, "脂肪_g": 1.6},
    "西兰花": {"热量_kcal": 36, "蛋白_g": 4.1, "碳水_g": 4.3, "脂肪_g": 0.6},
    "菠菜": {"热量_kcal": 28, "蛋白_g": 2.6, "碳水_g": 4.5, "脂肪_g": 0.3},
    "青菜": {"热量_kcal": 15, "蛋白_g": 1.5, "碳水_g": 2.7, "脂肪_g": 0.3},
    "番茄": {"热量_kcal": 19, "蛋白_g": 0.9, "碳水_g": 4.0, "脂肪_g": 0.2},
    "黄瓜": {"热量_kcal": 16, "蛋白_g": 0.8, "碳水_g": 3.6, "脂肪_g": 0.2},
    "苹果": {"热量_kcal": 52, "蛋白_g": 0.2, "碳水_g": 13.5, "脂肪_g": 0.2},
    "香蕉": {"热量_kcal": 93, "蛋白_g": 1.4, "碳水_g": 22.0, "脂肪_g": 0.2},
    "橙子": {"热量_kcal": 47, "蛋白_g": 0.9, "碳水_g": 11.8, "脂肪_g": 0.1},
    "葡萄": {"热量_kcal": 69, "蛋白_g": 0.7, "碳水_g": 18.1, "脂肪_g": 0.2},
    "牛奶": {"热量_kcal": 54, "蛋白_g": 3.0, "碳水_g": 3.4, "脂肪_g": 3.2},
    "酸奶": {"热量_kcal": 72, "蛋白_g": 2.5, "碳水_g": 9.3, "脂肪_g": 2.7},
    "全麦面包": {"热量_kcal": 246, "蛋白_g": 13.3, "碳水_g": 41.0, "脂肪_g": 4.2},
    "吐司": {"热量_kcal": 265, "蛋白_g": 8.3, "碳水_g": 49.0, "脂肪_g": 3.2},
    "燕麦片": {"热量_kcal": 389, "蛋白_g": 16.9, "碳水_g": 66.0, "脂肪_g": 6.9},
    "花生": {"热量_kcal": 567, "蛋白_g": 24.8, "碳水_g": 16.2, "脂肪_g": 44.3},
    "红薯": {"热量_kcal": 86, "蛋白_g": 1.6, "碳水_g": 20.1, "脂肪_g": 0.1},
    "土豆": {"热量_kcal": 77, "蛋白_g": 2.0, "碳水_g": 17.2, "脂肪_g": 0.2},
    "玉米": {"热量_kcal": 112, "蛋白_g": 4.0, "碳水_g": 22.8, "脂肪_g": 1.2},
    "牛油果": {"热量_kcal": 160, "蛋白_g": 2.0, "碳水_g": 8.5, "脂肪_g": 14.7},
    "批萨": {"热量_kcal": 266, "蛋白_g": 11.0, "碳水_g": 33.0, "脂肪_g": 10.0},
    "汉堡": {"热量_kcal": 295, "蛋白_g": 16.5, "碳水_g": 24.0, "脂肪_g": 14.0},
    "薯条": {"热量_kcal": 312, "蛋白_g": 3.4, "碳水_g": 41.0, "脂肪_g": 15.0},
    "可乐": {"热量_kcal": 43, "蛋白_g": 0.0, "碳水_g": 10.6, "脂肪_g": 0.0},
    "橄榄油": {"热量_kcal": 884, "蛋白_g": 0.0, "碳水_g": 0.0, "脂肪_g": 100.0},
    "黄油": {"热量_kcal": 717, "蛋白_g": 0.9, "碳水_g": 0.1, "脂肪_g": 81.0},
    "榴莲": {"热量_kcal": 150, "蛋白_g": 2.6, "碳水_g": 27.1, "脂肪_g": 3.3},
    "榴莲千层": {"热量_kcal": 260, "蛋白_g": 4.0, "碳水_g": 30.0, "脂肪_g": 15.0},
}

# 过敏原关键字 -> 过敏原分组
ALLERGEN_KEYWORDS = {
    "牛奶": "乳制品", "奶酪": "乳制品", "奶油": "乳制品", "乳": "乳制品",
    "鸡蛋": "蛋类", "蛋": "蛋类",
    "花生": "花生",
    "大豆": "大豆", "豆浆": "大豆", "豆腐": "大豆",
    "鱼": "鱼类",
    "虾": "甲壳类", "蟹": "甲壳类", "龙虾": "甲壳类",
    "小麦": "麸质", "面": "麸质", "面包": "麸质", "燕麦": "麸质",
}

# 库缺失时的通用回退估算（每 100g）
FALLBACK = {"热量_kcal": 100.0, "蛋白_g": 5.0, "碳水_g": 15.0, "脂肪_g": 3.0}

# 模糊家用单位：命中且无克数/无生活化描述/无状态时，视为"份量不明确"，强制澄清并问克数。
# 注意：若用户已给出生活化描述(portion_desc)或状态(portion_state)，则走 PORTION_MAP/默认兜底，不再硬拦截。
VAGUE_UNIT_KEYWORDS = ["碗", "盘", "块", "份", "勺", "捧", "碟", "盆", "杯"]

# 活动水平系数（TDEE = BMR * factor）
ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

# 目标热量缩放系数
GOAL_CALORIE_FACTOR = {"lose": 0.85, "maintain": 1.0, "gain": 1.15}
# 每公斤体重目标蛋白（g/kg）
GOAL_PROTEIN_PER_KG = {"lose": 1.8, "maintain": 1.4, "gain": 2.0}

# ============ 生活化份量参照映射（保留：普通碗 / 小碗 / 大碗 / 满碗 / 八分满 / 半碗 / 掌心 / 一拳 / 两拳 / 拇指）============
# 按食物大类分键，键为描述关键词，值为约合克数。
PORTION_MAP = {
    # 主食类（米、面、粥、粉、馒头、饼、薯、玉米等）—— 用碗/拳头衡量
    # 普通汤碗八分满（汤面/盖饭）约 200-250g；普通饭碗满碗约 150-200g
    "staple": {
        "满碗": 200, "八分满": 200, "半碗": 100, "普通碗": 175, "小碗": 100,
        "大碗": 250, "一碗": 175, "一拳": 150, "拳头": 150,
    },
    # 蛋白质类（肉、鱼、虾、蛋、豆腐等）—— 用掌心/块衡量
    "protein": {
        "掌心": 125, "一块": 125, "一小块": 100, "拳头": 125, "一拳": 125,
        "普通碗": 150, "小碗": 100, "大碗": 200,
    },
    # 蔬菜 / 水果 / 通用 —— 用拳/掌衡量
    "vegetable": {
        "两拳": 250, "一拳": 125, "一盘": 250, "一碟": 150,
    },
    "fruit": {
        "一拳": 125, "一个": 160, "两拳": 250,
    },
    "general": {
        "一拳": 125, "两拳": 250, "掌心": 125, "一勺": 12, "拇指": 12, "一小把": 25,
    },
}

# 食物大类关键词 -> 默认兜底克数（L3，用户仍说不知道时）。主食取普通餐食份量约 150-200g 中值。
PORTION_DEFAULT_GRAMS = {
    "staple": 200.0, "protein": 100.0, "vegetable": 150.0, "fruit": 120.0, "general": 120.0,
}

# 食物类型分类关键词
CATEGORY_KEYWORDS = {
    "staple": ["饭", "面", "粥", "粉", "馒头", "花卷", "包", "饼", "面包", "吐司", "薯", "玉米", "土豆", "燕麦", "蒙", "米"],
    "protein": ["鸡", "牛", "猪", "肉", "鱼", "虾", "蟹", "蛋", "豆腐", "豆干", "培根", "火腿", "排骨", "羊肉"],
    "vegetable": ["菜", "西兰花", "菠菜", "黄瓜", "番茄", "青椒", "萝卜", "木耳", "海带", "冬瓜", "茄子"],
    "fruit": ["果", "苹果", "香蕉", "橙", "橘", "梨", "桃", "葡萄", "草莓", "蓝莓", "西瓜", "芒果", "火龙果", "猕猴桃", "牛油果"],
}


def _round(v, nd=1):
    return round(float(v), nd)


def classify_food(name: str) -> str:
    """根据食物名判断大类（staple/protein/vegetable/fruit/general）。"""
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in name for k in kws):
            return cat
    return "general"


def match_portion_grams(desc: str, category: str) -> float:
    """从生活化描述中匹配克数：分类专属表优先，再到通用表；返回最长关键词匹配值，未命中返回 0。"""
    best_val = 0.0
    best_len = -1
    for table in (PORTION_MAP.get(category, {}), PORTION_MAP["general"]):
        if not desc:
            break
        for kw, grams in table.items():
            if kw in desc and len(kw) > best_len:
                best_len = len(kw)
                best_val = float(grams)
    return best_val


def parse_foods(foods_json):
    if isinstance(foods_json, str):
        data = json.loads(foods_json)
    else:
        data = foods_json
    if not isinstance(data, list):
        raise ValueError("foods 必须是 JSON 数组")
    out = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("foods 每个元素必须是对象")
        gram_val = item.get("grams", 0)
        grams = float(gram_val) if gram_val is not None else 0.0
        name = str(item.get("food", "")).strip()
        portion_desc = str(item.get("portion_desc", "") or "").strip()
        portion_state = str(item.get("portion_state", "") or "").strip()
        conf = item.get("confidence")
        out.append({
            "food": name,
            "grams": grams,
            "confidence": float(conf) if conf is not None else 1.0,
            "portion_desc": portion_desc,
            "portion_state": portion_state,
        })
    return out


def compute(foods, profile):
    risk_flags = []
    needs_clarification = False
    clarification_type = "none"  # none | grams | estimate
    totals = {"热量_kcal": 0.0, "蛋白_g": 0.0, "碳水_g": 0.0, "脂肪_g": 0.0}
    items = []

    for f in foods:
        name = f["food"]
        grams = f["grams"]
        conf = f["confidence"]
        portion_desc = f.get("portion_desc", "")
        portion_state = f.get("portion_state", "")
        category = classify_food(name)

        # ============ L2：用户说"不知道/不清楚/没称过" -> 引导进参照物估算 ============
        if portion_state == "unknown":
            needs_clarification = True
            if clarification_type == "none":
                clarification_type = "estimate"
            items.append({
                "food": name, "matched_key": name, "grams": 0.0,
                "calories": 0.0, "protein": 0.0, "carb": 0.0, "fat": 0.0,
                "confidence": conf, "_needs_clarification": True,
            })
            continue

        # ============ L3：用户仍说不知道 -> 取默认值兜底，confidence=0.4，附 ±20% ============
        if portion_state == "unknown_still":
            dg = PORTION_DEFAULT_GRAMS.get(category, PORTION_DEFAULT_GRAMS["general"])
            grams = dg
            conf = 0.4
            risk_flags.append({
                "type": "portion_estimated", "level": "warning",
                "message": f"「{name}」按普通份量估算约{dg:g}g（你可能没有称重），可能有±20%误差，建议稍后修正",
            })

        # ============ 明确克数（L0）优先：直接计算，不查 PORTION_MAP ============
        # 生活化描述（L1）则查 PORTION_MAP 映射克数，confidence=0.6
        elif grams > 0:
            # 明确克数，保持原 confidence，直接计算
            pass
        elif portion_desc:
            mapped = match_portion_grams(portion_desc, category)
            if mapped > 0:
                grams = mapped
                conf = 0.6
                risk_flags.append({
                    "type": "portion_estimated", "level": "info",
                    "message": f"「{name}」根据生活化描述「{portion_desc}」映射约{mapped:g}g，置信度约0.6，可能有误差",
                })
            else:
                # 生活化描述无法映射 -> 仍需澄清克数
                needs_clarification = True
                if clarification_type == "none":
                    clarification_type = "grams"
                items.append({
                    "food": name, "matched_key": name, "grams": 0.0,
                    "calories": 0.0, "protein": 0.0, "carb": 0.0, "fat": 0.0,
                    "confidence": conf, "_needs_clarification": True,
                })
                continue
        else:
            # 模糊单位且无克数/无描述/无状态 -> 强制问克数
            if any(k in name for k in VAGUE_UNIT_KEYWORDS) or grams <= 0:
                needs_clarification = True
                if clarification_type == "none":
                    clarification_type = "grams"
                items.append({
                    "food": name, "matched_key": name, "grams": 0.0,
                    "calories": 0.0, "protein": 0.0, "carb": 0.0, "fat": 0.0,
                    "confidence": conf, "_needs_clarification": True,
                })
                continue

        # 模型置信度低（非估算路径）-> 澄清确认
        if conf < 0.8 and portion_state != "unknown_still" and not portion_desc:
            needs_clarification = True
            if clarification_type == "none":
                clarification_type = "grams"
            risk_flags.append({
                "type": "low_confidence", "level": "warning",
                "message": f"识别置信度较低（{conf:.2f}），请向用户确认「{name}」的份量是否正确",
            })

        # 精确匹配，其次子串匹配
        food_key = None
        if name in FOOD_DB:
            food_key = name
        else:
            for key in FOOD_DB:
                if key in name or name in key:
                    food_key = key
                    break

        if food_key:
            per100 = FOOD_DB[food_key]
        else:
            per100 = FALLBACK
            risk_flags.append({
                "type": "nutrition_lookup_miss", "level": "tip",
                "message": f"营养库未收录「{name}」，已按通用估算值计算，建议人工核对",
            })

        factor = grams / 100.0 if grams > 0 else 0.0
        item = {
            "food": name,
            "matched_key": food_key or name,
            "grams": _round(grams) if grams else 0.0,
            "calories": _round(per100["热量_kcal"] * factor),
            "protein": _round(per100["蛋白_g"] * factor),
            "carb": _round(per100["碳水_g"] * factor),
            "fat": _round(per100["脂肪_g"] * factor),
            "confidence": conf,
        }
        items.append(item)
        for k in totals:
            totals[k] += per100[k] * factor

        # 过敏原子串匹配：优先保障过敏安全，触发即标记 high（去重）
        for kw, group in ALLERGEN_KEYWORDS.items():
            if kw in name:
                if not any(r.get("type") == "allergen_alert" and group in r.get("message", "") for r in risk_flags):
                    risk_flags.append({
                        "type": "allergen_alert", "level": "high",
                        "message": f"「{name}」可能含有{group}，若用户对其过敏请避免食用",
                    })

    calories = _round(totals["热量_kcal"])
    protein = _round(totals["蛋白_g"])
    carb = _round(totals["碳水_g"])
    fat = _round(totals["脂肪_g"])

    # 需要澄清时：热量/宏量一律归零，禁止输出任何估算数字（除非有 portion_estimated 的真实估算）
    # 注意：L1/L3 估算仍会继续计算 calories；只有真正需要澄清（grams/estimate）时才归零。
    if needs_clarification and not any(r.get("type") == "portion_estimated" for r in risk_flags):
        calories = 0.0
        protein = 0.0
        carb = 0.0
        fat = 0.0

    # Mifflin-St Jeor 计算 BMR 与目标热量
    weight = float(profile["weight_kg"])
    height = float(profile["height_cm"])
    age = float(profile["age"])
    gender = profile["gender"]
    activity = profile["activity_level"]
    goal = profile["goal_type"]
    bmr = 10 * weight + 6.25 * height - 5 * age + (5 if gender == "male" else -161)
    tdee = bmr * ACTIVITY_FACTORS.get(activity, 1.375)
    target_calories = int(round(tdee * GOAL_CALORIE_FACTOR.get(goal, 1.0)))
    target_protein = _round(weight * GOAL_PROTEIN_PER_KG.get(goal, 1.4), 0)
    target_fat = int(round(target_calories * 0.25 / 9.0))
    target_carb = int(round((target_calories - target_protein * 4 - target_fat * 9) / 4.0))

    remaining_calories = _round(target_calories - calories)
    pct_consumed = _round(calories / target_calories * 100) if target_calories > 0 else 0.0

    if not needs_clarification and calories < 200:
        risk_flags.append({
            "type": "low_calorie_reminder", "level": "warning",
            "message": "本餐热量估算值过低，请向用户确认份量信息是否完整",
        })

    return {
        "status": "success",
        "calories": calories,
        "protein": protein,
        "carb": carb,
        "fat": fat,
        "target_calories": target_calories,
        "target_protein": target_protein,
        "target_carb": target_carb,
        "target_fat": target_fat,
        "remaining_calories": remaining_calories,
        "pct_consumed": pct_consumed,
        "needs_clarification": needs_clarification,
        "clarification_type": clarification_type,
        "risk_flags": risk_flags,
        "items": items,
    }


def main():
    parser = argparse.ArgumentParser(description="确定性营养计算工具")
    parser.add_argument("--foods", required=True,
                        help="结构化食物明细 JSON 数组字符串，如 [{\"food\":\"米饭\",\"grams\":200,\"confidence\":0.95}]")
    parser.add_argument("--age", type=float, default=30.0, help="年龄")
    parser.add_argument("--gender", default="male", choices=["male", "female"], help="性别")
    parser.add_argument("--height", type=float, default=170.0, help="身高(cm)")
    parser.add_argument("--weight", type=float, default=65.0, help="体重(kg)")
    parser.add_argument("--activity", default="light",
                        choices=["sedentary", "light", "moderate", "active", "very_active"], help="活动水平")
    parser.add_argument("--goal", default="maintain", choices=["lose", "maintain", "gain"], help="目标")
    args = parser.parse_args()

    try:
        foods = parse_foods(args.foods)
        profile = {
            "age": args.age,
            "gender": args.gender,
            "height_cm": args.height,
            "weight_kg": args.weight,
            "activity_level": args.activity,
            "goal_type": args.goal,
        }
        result = compute(foods, profile)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        err = {"status": "error", "message": str(exc)}
        print(json.dumps(err, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()