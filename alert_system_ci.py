"""
alert_system_ci.py — GitHub Actions 版本
数据源：Yahoo Finance（对服务器请求友好，无封锁）
"""

import os, sys, requests, time, argparse, logging
from datetime import datetime, date

SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("alert_log.txt", encoding="utf-8"),
    ],
)
log = logging.getLogger()

YAHOO_SYMBOLS = {
    "WTI原油":    "CL=F",
    "布伦特原油": "BZ=F",
}

ALERT_RULES = [
    {"name": "WTI 原油",  "key": "WTI原油",    "unit": "USD/桶", "pct": 3.0, "abs_low": 65.0, "abs_high": 90.0, "note": "影响燃油附加费"},
    {"name": "布伦特原油", "key": "布伦特原油", "unit": "USD/桶", "pct": 3.0, "abs_low": None,  "abs_high": 95.0, "note": "国际油价基准"},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

def fetch_yahoo(symbol, name):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        r = requests.get(url, headers=HEADERS, params={"interval": "1d", "range": "5d"}, timeout=15)
        r.raise_for_status()
        closes = r.json()["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if len(closes) < 2:
            return None
        curr, prev = closes[-1], closes[-2]
        chg = curr - prev
        pct = round(chg / prev * 100, 2)
        log.info(f"  ✅ {name}: {curr:.2f}  {pct:+.2f}%")
        return {"value": curr, "change": chg, "change_pct": pct}
    except Exception as e:
        log.warning(f"  ❌ {name} 失败: {e}")
        return None

def fetch_bdi(name):
    """从 investing.com 获取 BDI 系列"""
    pid_map = {"波罗的海干散货 BDI": "959", "巴拿马型指数 BPI": "962", "灵便型指数 BSI": "2188"}
    pid = pid_map.get(name)
    if not pid:
        return None
    try:
        url = f"https://api.investing.com/api/financialdata/{pid}/historical/chart/"
        r = requests.get(url, headers={**HEADERS, "domain-id": "www", "Referer": "https://www.investing.com/"},
                         params={"period": "P1W", "interval": "P1D", "pointscount": 5}, timeout=15)
        prices = r.json().get("data", [])
        if len(prices) >= 2:
            curr, prev = float(prices[-1][2]), float(prices[-2][2])
            chg = curr - prev
            pct = round(chg / prev * 100, 2)
            log.info(f"  ✅ {name}: {curr:.0f}  {pct:+.2f}%")
            return {"value": curr, "change": chg, "change_pct": pct}
    except Exception as e:
        log.warning(f"  ❌ {name} 失败: {e}")
    return None

def push_wechat(title, content):
    if not SERVERCHAN_KEY:
        log.info(f"  [Server酱] 未配置 Key，跳过\n  标题: {title}")
        return
    try:
        r = requests.post(f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send",
                          data={"title": title, "desp": content}, timeout=15)
        code = r.json().get("code")
        log.info(f"  {'✅' if code == 0 else '❌'} 微信推送: {title}  code={code}")
    except Exception as e:
        log.warning(f"  ❌ 推送错误: {e}")

def check_rule(rule, data):
    alerts = []
    v, pct = data["value"], data["change_pct"]
    if abs(pct) >= rule["pct"]:
        tag = "🔴 暴跌" if pct < 0 else "🟢 急涨"
        alerts.append(f"{tag} **{rule['name']}** 单日 {pct:+.2f}%\n  当前：{v:,.1f} {rule['unit']}  {rule['note']}")
    if rule.get("abs_low") and v < rule["abs_low"]:
        alerts.append(f"⚠️ **{rule['name']}** 跌破 {rule['abs_low']:,}\n  当前：{v:,.1f} {rule['unit']}")
    if rule.get("abs_high") and v > rule["abs_high"]:
        alerts.append(f"🚨 **{rule['name']}** 突破 {rule['abs_high']:,}\n  当前：{v:,.1f} {rule['unit']}")
    return alerts

def daily_summary(index_data):
    lines = [f"**航运早报** · {date.today().strftime('%Y年%m月%d日')}", "", "**今日核心指数**", "```"]
    for name, d in index_data.items():
        if d:
            arrow = "↑" if d["change_pct"] >= 0 else "↓"
            lines.append(f"{name:<18} {d['value']:>9,.1f}   {arrow}{abs(d['change_pct']):.1f}%")
    lines += ["```", "", "*数据来源：Yahoo Finance / Investing.com · 自动推送*"]
    return "\n".join(lines)

def run(send_summary=False):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    log.info(f"\n{'='*50}\n  航运预警系统  {now}\n{'='*50}")
    log.info("\n[1] 抓取指数数据...")

    index_data = {}
    # Yahoo Finance 数据（油价）
    for rule in ALERT_RULES:
        sym = YAHOO_SYMBOLS.get(rule["key"])
        index_data[rule["name"]] = fetch_yahoo(sym, rule["name"]) if sym else None
        time.sleep(0.5)

    # BDI 系列
    for name in ["波罗的海干散货 BDI", "巴拿马型指数 BPI", "灵便型指数 BSI"]:
        index_data[name] = fetch_bdi(name)
        time.sleep(0.5)

    log.info("\n[2] 检查预警规则...")
    all_alerts = []
    for rule in ALERT_RULES:
        d = index_data.get(rule["name"])
        if not d:
            log.info(f"  跳过 {rule['name']}（无数据）")
            continue
        alerts = check_rule(rule, d)
        all_alerts.extend(alerts)
        log.info(f"  {rule['name']}: {'⚠️ '+str(len(alerts))+'条预警' if alerts else '✓ 正常'}")

    if all_alerts:
        log.info(f"\n[3] 推送 {len(all_alerts)} 条预警...")
        push_wechat(f"🚨 航运预警 ({len(all_alerts)}条)",
                    "\n\n".join(all_alerts) + f"\n\n---\n*{now} 自动检测*")
    else:
        log.info("\n[3] 无预警触发，市场平稳，静默")

    if send_summary:
        log.info("\n[4] 推送每日早报...")
        push_wechat("📊 航运早报", daily_summary(index_data))

    log.info(f"\n✅ 完成  {now}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    run(send_summary=parser.parse_args().summary)
