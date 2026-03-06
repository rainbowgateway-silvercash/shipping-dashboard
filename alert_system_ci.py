"""
alert_system_ci.py
──────────────────
GitHub Actions 专用版本。
和 alert_system.py 逻辑完全一样，唯一区别：
  Key 从"环境变量"读取，而不是硬写在代码里。

GitHub Actions 运行时会自动把 Secrets 注入为环境变量，
所以这个文件本身不含任何密钥，可以安全公开存放。
"""

import os
import sys
import requests
import time
import argparse
import logging
from datetime import datetime, date

# ── 从环境变量读取密钥（GitHub Actions 自动注入）──
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")
WECOM_WEBHOOK  = os.environ.get("WECOM_WEBHOOK", "")

# ── 日志：同时输出到控制台和文件 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("alert_log.txt", encoding="utf-8"),
    ],
)
log = logging.getLogger()

# ════════════════════════════════════════
# 预警规则（和 alert_system.py 保持一致）
# ════════════════════════════════════════
ALERT_RULES = [
    {
        "name":      "波罗的海干散货 BDI",
        "symbol":    "BDIY.I",
        "unit":      "点",
        "pct":       3.0,    # 单日涨跌幅阈值
        "week_pct":  8.0,    # 周累计阈值
        "abs_low":   1000,   # 跌破预警
        "abs_high":  3000,   # 突破预警
        "note":      "影响澳洲煤/铁矿石回程运价",
    },
    {
        "name":      "巴拿马型指数 BPI",
        "symbol":    "BPIY.I",
        "unit":      "点",
        "pct":       4.0,
        "week_pct":  10.0,
        "abs_low":   None,
        "abs_high":  None,
        "note":      "影响巴拿马型和灵便型船租金",
    },
    {
        "name":      "WTI 原油",
        "symbol":    "CL.F",
        "unit":      "USD/桶",
        "pct":       3.0,
        "week_pct":  None,
        "abs_low":   65.0,
        "abs_high":  90.0,
        "note":      "影响燃油附加费(BAF)和运营成本",
    },
    {
        "name":      "布伦特原油",
        "symbol":    "CB.F",
        "unit":      "USD/桶",
        "pct":       3.0,
        "week_pct":  None,
        "abs_low":   None,
        "abs_high":  95.0,
        "note":      "国际油价基准，影响成品油轮运价",
    },
    {
        "name":      "灵便型指数 BSI",
        "symbol":    "BSIY.I",
        "unit":      "点",
        "pct":       4.0,
        "week_pct":  10.0,
        "abs_low":   None,
        "abs_high":  None,
        "note":      "影响小型散货船和件杂货船租金",
    },
]

# ════════════════════════════════════════
# 数据获取
# ════════════════════════════════════════
def fetch_stooq(symbol):
    """从 Stooq.com 获取指数最新价（免费，无需 API Key）"""
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        lines = r.text.strip().split("\n")
        if len(lines) < 3:
            return None
        last = lines[-1].split(",")
        prev = lines[-2].split(",")
        if len(last) < 5:
            return None
        close  = float(last[4])
        p_close = float(prev[4])
        chg    = close - p_close
        pct    = round(chg / p_close * 100, 2)
        week_start = float(lines[-6].split(",")[4]) if len(lines) >= 6 else p_close
        week_pct   = round((close - week_start) / week_start * 100, 2)
        return {"value": close, "change": chg, "change_pct": pct,
                "week_pct": week_pct, "date": last[0]}
    except Exception as e:
        log.warning(f"  [Stooq] {symbol} 失败: {e}")
        return None

# ════════════════════════════════════════
# 推送
# ════════════════════════════════════════
def push_wechat(title, content):
    """通过 Server酱 推送到微信"""
    if not SERVERCHAN_KEY:
        log.info(f"  [Server酱] 未配置 Key，仅打印:\n  标题: {title}")
        return
    url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
    try:
        r = requests.post(url, data={"title": title, "desp": content}, timeout=15)
        result = r.json()
        if result.get("code") == 0:
            log.info(f"  [Server酱] ✅ 推送成功: {title}")
        else:
            log.warning(f"  [Server酱] 推送失败: {result}")
    except Exception as e:
        log.warning(f"  [Server酱] 错误: {e}")

# ════════════════════════════════════════
# 预警检测
# ════════════════════════════════════════
def check_rule(rule, data):
    alerts = []
    v   = data["value"]
    pct = data["change_pct"]
    wpct = data["week_pct"]

    if abs(pct) >= rule["pct"]:
        tag = "🔴 暴跌" if pct < 0 else "🟢 急涨"
        alerts.append(
            f"{tag} **{rule['name']}** 单日 {pct:+.2f}%\n"
            f"  当前值：{v:,.1f} {rule['unit']}  {rule['note']}"
        )
    if rule["week_pct"] and abs(wpct) >= rule["week_pct"]:
        tag = "📉 周跌" if wpct < 0 else "📈 周涨"
        alerts.append(
            f"{tag} **{rule['name']}** 一周累计 {wpct:+.2f}%\n"
            f"  当前值：{v:,.1f} {rule['unit']}"
        )
    if rule["abs_low"] and v < rule["abs_low"]:
        alerts.append(
            f"⚠️ **{rule['name']}** 跌破 {rule['abs_low']:,}\n"
            f"  当前：{v:,.1f} {rule['unit']}  {rule['note']}"
        )
    if rule["abs_high"] and v > rule["abs_high"]:
        alerts.append(
            f"🚨 **{rule['name']}** 突破 {rule['abs_high']:,}\n"
            f"  当前：{v:,.1f} {rule['unit']}  {rule['note']}"
        )
    return alerts

# ════════════════════════════════════════
# 每日早报
# ════════════════════════════════════════
def daily_summary(index_data):
    today = date.today().strftime("%Y年%m月%d日")
    lines = [f"**航运早报** · {today}", "", "**今日核心指数**", "```"]
    items = [
        ("BDI  波罗的海", "BDIY.I"),
        ("BPI  巴拿马型", "BPIY.I"),
        ("BSI  灵便型  ", "BSIY.I"),
        ("WTI  原油价格", "CL.F"),
        ("Brent 布伦特 ", "CB.F"),
    ]
    for label, sym in items:
        d = index_data.get(sym)
        if d:
            arrow = "↑" if d["change_pct"] >= 0 else "↓"
            lines.append(f"{label}  {d['value']:>9,.1f}   {arrow}{abs(d['change_pct']):.1f}%")
    lines += ["```", "", "*数据来源：Stooq.com · 自动推送*"]
    return "\n".join(lines)

# ════════════════════════════════════════
# 主逻辑
# ════════════════════════════════════════
def run(send_summary=False):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    log.info(f"\n{'='*50}\n  航运预警系统  {now}\n{'='*50}")

    # 1. 抓取数据
    log.info("\n[1] 抓取指数数据...")
    index_data = {}
    for rule in ALERT_RULES:
        sym = rule["symbol"]
        d = fetch_stooq(sym)
        if d:
            index_data[sym] = d
            log.info(f"  ✅ {rule['name']}: {d['value']:,.1f}  {d['change_pct']:+.2f}%")
        else:
            log.info(f"  ❌ {rule['name']}: 获取失败")
        time.sleep(0.5)

    # 2. 检查预警
    log.info("\n[2] 检查预警规则...")
    all_alerts = []
    for rule in ALERT_RULES:
        d = index_data.get(rule["symbol"])
        if not d:
            continue
        alerts = check_rule(rule, d)
        all_alerts.extend(alerts)
        status = f"⚠️  {len(alerts)} 条预警" if alerts else "✓  正常"
        log.info(f"  {rule['name']}: {status}")

    # 3. 推送预警
    if all_alerts:
        log.info(f"\n[3] 推送 {len(all_alerts)} 条预警...")
        content = "\n\n".join(all_alerts) + f"\n\n---\n*{now} 自动检测*"
        push_wechat(f"🚨 航运预警 ({len(all_alerts)}条)", content)
    else:
        log.info("\n[3] 无预警触发，市场平稳，静默")

    # 4. 每日早报
    if send_summary:
        log.info("\n[4] 推送每日早报...")
        push_wechat("📊 航运早报", daily_summary(index_data))

    log.info(f"\n✅ 完成  {now}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true", help="同时发送每日早报")
    args = parser.parse_args()
    run(send_summary=args.summary)
