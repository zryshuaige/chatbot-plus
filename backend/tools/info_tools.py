"""实时信息类工具：天气 / 汇率 / IP 定位 / 时间日期。全部免 API key。

设计要点：
- 每个工具 try/except 自愈，失败返回可读错误串而非抛异常（避免模型因异常反复重试触发循环）；
- 外部请求统一 timeout；
- 结果走轻量 TTL 缓存（默认 10 分钟），重复问省调用、提速。
"""
from __future__ import annotations

import time
from datetime import datetime
from functools import wraps
from typing import Any, Callable

import requests

from langchain.tools import tool

# ---------------- 轻量 TTL 缓存 ----------------
_CACHE: dict[str, tuple[float, Any]] = {}


def cached(ttl: float):
    """装饰器：按 (函数名+args+kwargs) 做 TTL 缓存。ttl 秒。

    只缓存成功结果（返回字符串的“成功”判定：不以“失败/错误”字样开头），
    失败结果不缓存，保证下次重试。"""
    def deco(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{fn.__name__}|{args}|{sorted(kwargs.items())}"
            now = time.monotonic()
            hit = _CACHE.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
            val = fn(*args, **kwargs)
            # 失败不缓存
            if isinstance(val, str) and (val.startswith("查询失败") or val.startswith("获取失败")):
                return val
            _CACHE[key] = (now, val)
            return val
        return wrapper
    return deco


# 默认缓存时长（秒）
_DEFAULT_TTL = 600


# ---------------- 天气 ----------------
@cached(_DEFAULT_TTL)
def _fetch_weather(city: str) -> str:
    r = requests.get(f"https://wttr.in/{city}?format=j1", timeout=20)
    r.raise_for_status()
    d = r.json()
    cur = d["current_condition"][0]
    desc = cur["weatherDesc"][0]["value"]
    days = d.get("weather", [])
    lines = [
        f"📍 {city}",
        f"现在：{cur['temp_C']}°C（体感 {cur['FeelsLikeC']}°C），{desc}，"
        f"湿度 {cur['humidity']}%，风速 {cur['windspeedKmph']}km/h，能见度 {cur['visibility']}km。",
        "未来预报：",
    ]
    for day in days[:3]:
        date = day.get("date", "")
        lines.append(
            f"  · {date}：{day.get('mintempC')}~{day.get('maxtempC')}°C，"
            f"{day.get('hourly', [{}])[4].get('weatherDesc', [{}])[0].get('value', '')}（午间）"
        )
    return "\n".join(lines)


@tool
def get_weather(city: str) -> str:
    """查询某城市当前天气与未来 3 天预报（温度、天气状况、湿度、风速）。
    适合用户问“XX天气怎样 / 冷不冷 / 要不要带伞 / 穿什么”。

    Args:
        city: 城市名，中英文均可，如 "杭州" "上海" "Beijing"。
    """
    try:
        return _fetch_weather(city)
    except Exception as e:
        return f"查询失败：无法获取「{city}」的天气（{e}）。可换个城市名再试。"


# ---------------- 汇率 ----------------
@cached(_DEFAULT_TTL)
def _fetch_rate(base: str, target: str) -> str:
    r = requests.get(f"https://open.er-api.com/v6/latest/{base.upper()}", timeout=20)
    r.raise_for_status()
    d = r.json()
    rates = d.get("rates", {})
    rate = rates.get(target.upper())
    if rate is None:
        return f"查询失败：不支持的目标货币 {target}。常用：CNY USD EUR JPY HKD GBP KRW。"
    return f"1 {base.upper()} = {rate} {target.upper()}（更新时间 {d.get('time_last_update_utc','')[:16]}）"


@tool
def get_exchange_rate(from_currency: str, to_currency: str) -> str:
    """查询两种货币之间的实时汇率。
    适合用户问“美元兑人民币多少 / 100 日元等于多少人民币”等。

    Args:
        from_currency: 源货币代码，如 USD、CNY、JPY、EUR。
        to_currency: 目标货币代码，同上。
    """
    try:
        return _fetch_rate(from_currency, to_currency)
    except Exception as e:
        return f"查询失败：获取 {from_currency}->{to_currency} 汇率失败（{e}）。"


# ---------------- IP 定位 ----------------
@cached(_DEFAULT_TTL)
def _fetch_ip(ip: str) -> dict:
    url = "http://ip-api.com/json/" + (ip or "")
    r = requests.get(url, params={"lang": "zh-CN"}, timeout=20)
    r.raise_for_status()
    return r.json()


@tool
def get_ip_info(ip: str = "") -> str:
    """根据 IP 地址查询归属地（国家/省/市、ISP、时区、经纬度）。不传 ip 则查询当前网络出口 IP。
    适合用户问“我的 IP 是哪里的 / 这个 IP 归属哪里”。

    Args:
        ip: 可选的 IPv4 地址，如 "8.8.8.8"；留空查询当前出口 IP。
    """
    try:
        d = _fetch_ip(ip)
        if d.get("status") != "success":
            return f"查询失败：{d.get('message', '未知错误')}。"
        return (
            f"IP {d.get('query')}：{d.get('country')} {d.get('regionName')} {d.get('city')}，"
            f"ISP={d.get('isp')}，时区={d.get('timezone')}，"
            f"经纬度=({d.get('lat')}, {d.get('lon')})。"
        )
    except Exception as e:
        return f"查询失败：IP 归属地查询失败（{e}）。"


# ---------------- 时间日期 ----------------
@tool
def get_current_time() -> str:
    """获取当前系统时间（年月日时分秒 + 星期）。无需参数。
    适合用户问“现在几点 / 今天星期几 / 今天日期”。"""
    now = datetime.now()
    week = "一二三四五六日"[now.weekday()]
    return now.strftime(f"当前时间：%Y年%m月%d日 %H:%M:%S 星期{week}")


@tool
def get_date_info() -> str:
    """获取今日的详细日期信息（公历日期、星期、距年底天数）。无需参数。
    适合用户问“今天几号 / 距年底还有多少天 / 这周几”。"""
    now = datetime.now()
    week = "一二三四五六日"[now.weekday()]
    end_of_year = datetime(now.year, 12, 31)
    days_left = (end_of_year - now).days
    day_of_year = now.timetuple().tm_yday
    head = now.strftime("今天是 %Y年%m月%d日 星期") + week + "，"
    return f"{head}是今年的第 {day_of_year} 天，距年底还有 {days_left} 天。"


# 暴露给注册表
INFO_TOOLS = [get_weather, get_exchange_rate, get_ip_info, get_current_time, get_date_info]
