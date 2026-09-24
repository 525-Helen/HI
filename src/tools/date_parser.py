"""相对日期解析工具。

将自然语言中的相对日期文本（如"今天/昨天/前天/上周三/三天前/上个月"）解析为
具体的 YYYY-MM-DD 日期字符串。用于餐食记录、历史查询等场景的时间归一化。
"""
import datetime
import re
from typing import Optional

# 指代不明的日期短语：无法确定具体是哪一天，必须追问，禁止臆测/禁止保存。
AMBIGUOUS_DATE_PHRASES = [
    "那天", "那一天", "某天", "某日", "之前那次", "上次那次", "上回那",
    "那一次", "那一天中午", "那天晚上", "那天早上",
]


def is_ambiguous_date(text: str) -> bool:
    """判断文本是否包含指代不明的日期（如"那天/某天/之前那次"）。

    此类日期无法解析为具体 YYYY-MM-DD，流程应返回 meal_date=null 并要求用户确认。
    """
    if not text:
        return False
    return any(p in text for p in AMBIGUOUS_DATE_PHRASES)


WEEKDAY_MAP = {
    "一": 0, "1": 0, "周一": 0, "星期一": 0,
    "二": 1, "2": 1, "周二": 1, "星期二": 1,
    "三": 2, "3": 2, "周三": 2, "星期三": 2,
    "四": 3, "4": 3, "周四": 3, "星期四": 3,
    "五": 4, "5": 4, "周五": 4, "星期五": 4,
    "六": 5, "6": 5, "周六": 5, "星期六": 5,
    "日": 6, "天": 6, "0": 6, "周日": 6, "星期天": 6,
}


def _parse_weekday_keyword(text: str) -> Optional[int]:
    """从文本中提取"周X/星期X"的星期索引（0=周一 ... 6=周日），取最后一个匹配。"""
    matches = re.findall(r"(?:周|星期)([一二三四五六日天1-7])", text)
    if not matches:
        return None
    key = matches[-1]
    if key in "1234567":
        key = {"1": "一", "2": "二", "3": "三", "4": "四", "5": "五", "6": "六", "7": "日"}[key]
    return WEEKDAY_MAP.get(key)


def _prev_month(ref: datetime.date) -> datetime.date:
    """返回 ref 所在日期的上一个月同日（若上月无该日则取上月最后一天）。"""
    year, month = ref.year, ref.month
    if month == 1:
        year, month = year - 1, 12
    else:
        month -= 1
    # 上月最后一天
    if month == 12:
        last = datetime.date(year, 12, 31)
    else:
        last = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    day = min(ref.day, last.day)
    return datetime.date(year, month, day)


def parse_relative_date(text: str, reference_date: Optional[datetime.date] = None) -> Optional[str]:
    """把相对日期文本解析为 YYYY-MM-DD。

    支持：今天/昨日/昨天/前天/大前天/N 天前/上周一~周日/本周一~周日/上个月。
    无法解析时返回 None。
    """
    if not text:
        return None
    ref = reference_date or datetime.date.today()
    t = text.strip()
    # 已存在的绝对日期，直接放行
    m = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime.date(y, mo, d).isoformat()
        except ValueError:
            return None

    # 今天/今日
    if re.search(r"(今天|今日)", t):
        return ref.isoformat()
    # 昨天/昨日
    if re.search(r"(昨天|昨日)", t):
        return (ref - datetime.timedelta(days=1)).isoformat()
    # 大前天（必须先于"前天"判断，避免被"前天"子串吸收）
    if re.search(r"大前天", t):
        return (ref - datetime.timedelta(days=3)).isoformat()
    # 前天/前一天
    if re.search(r"(前天|前一天)", t):
        return (ref - datetime.timedelta(days=2)).isoformat()
    # N 天前 / 三·五·十天前（支持中文数字 1-10）
    m = re.search(r"([0-9一二三四五六七八九十]+)\s*(?:天|日)(?:前|以前)?", t)
    if m:
        num = int({"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                   "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}.get(m.group(1), m.group(1) or "0"))
        return (ref - datetime.timedelta(days=num)).isoformat()

    # 上一/上个/上周/上个星期 + 周X
    if re.search(r"(上周|上个星期|上周星期|上一周|上个周)", t):
        idx = _parse_weekday_keyword(t)
        if idx is not None:
            this_monday = ref - datetime.timedelta(days=ref.weekday())
            last_monday = this_monday - datetime.timedelta(days=7)
            return (last_monday + datetime.timedelta(days=idx)).isoformat()

    # 本周/这周/这个星期 + 周X
    if re.search(r"(本周|这周|这个星期|这星期)", t):
        idx = _parse_weekday_keyword(t)
        if idx is not None:
            this_monday = ref - datetime.timedelta(days=ref.weekday())
            return (this_monday + datetime.timedelta(days=idx)).isoformat()

    # 上个星期（无具体周X时默认取上个自然周一）
    if re.search(r"(上个星期|上一周)", t):
        this_monday = ref - datetime.timedelta(days=ref.weekday())
        return (this_monday - datetime.timedelta(days=7)).isoformat()

    # 上个月/上月
    if re.search(r"(上个月|上月)", t):
        return _prev_month(ref).isoformat()

    return None