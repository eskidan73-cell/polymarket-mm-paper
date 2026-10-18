"""Бумажный маркет-мейкинг на Polymarket: ничего не торгует, только моделирует.

Раз в запуск: выбирает несколько рынков, держит виртуальные заявки на покупку YES
(bid = mid - OFFSET) и на покупку NO (эквивалент продажи YES по ask = mid + OFFSET),
исполнение берёт из реальной ленты сделок: заявка считается исполненной, если
проходит сделка по цене, пересекающей нашу. Два режима:
  strict - сделка строго через нашу цену (пессимистично, очередь впереди нас);
  touch  - сделка по нашей цене или лучше (оптимистично).
Награды за ликвидность и rebates не начисляются, а оцениваются отдельно по
fee_equiv исполнений. P&L считается по mid (mark-to-market).
"""
import json, os, time
from datetime import datetime, timezone
import requests

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"
STATE = os.environ.get("MM_STATE", "mm_state.json")
LOG = os.environ.get("MM_LOG", "mm_log.jsonl")

N_MARKETS = 6
OFFSET = 0.01          # отступ от mid (1 цент)
INV_CAP = 300.0        # макс. чистый инвентарь в фишках YES, после него одну сторону не котируем
MODES = ("strict", "touch")


def get(url, **p):
    r = requests.get(url, params=p, timeout=20)
    r.raise_for_status()
    return r.json()


def select_markets():
    now = datetime.now(timezone.utc)
    out = []
    for off in (0, 100, 200):
        for m in get(GAMMA, active="true", closed="false", limit=100, offset=off,
                     order="volume24hr", ascending="false"):
            try:
                if not m.get("acceptingOrders") or not m.get("enableOrderBook"):
                    continue
                end = datetime.fromisoformat(m["endDate"].replace("Z", "+00:00"))
                days = (end - now).total_seconds() / 86400
                bb, ba = float(m.get("bestBid") or 0), float(m.get("bestAsk") or 0)
                mid = (bb + ba) / 2
                rs, rms = float(m.get("rewardsMinSize") or 0), float(m.get("rewardsMaxSpread") or 0)
                v = float(m.get("volume24hr") or 0)
                if not (3 <= days <= 90 and 0.2 <= mid <= 0.8 and 0 < ba - bb <= 0.02):
                    continue
                if not (0 < rs <= 100 and rms >= 3 and 20_000 <= v <= 500_000):
                    continue
                out.append({"cid": m["conditionId"], "q": m["question"][:70],
                            "tok": json.loads(m["clobTokenIds"])[0], "min_size": rs,
                            "max_spread": rms, "v24": v})
            except Exception:
                continue
    out.sort(key=lambda x: -x["v24"])
    return out[:N_MARKETS]


def book_mid(tok):
    b = get(f"{CLOB}/book", token_id=tok)
    bid = max((float(x["price"]) for x in b["bids"]), default=None)
    ask = min((float(x["price"]) for x in b["asks"]), default=None)
    if bid is None or ask is None:
        return None, None
    return (bid + ask) / 2, float(b.get("tick_size") or 0.01)


def fills(mode, bid, ask, size, trades, tok):
    """trades: ленты по YES-токену. Возвращает (куплено YES по bid, продано YES по ask)."""
    bought = sold = 0.0
    for t in trades:
        if t.get("asset") != tok:
            continue
        p, s = float(t["price"]), float(t["size"])
        hit_bid = (p < bid) if mode == "strict" else (p <= bid)
        hit_ask = (p > ask) if mode == "strict" else (p >= ask)
        if t["side"] == "SELL" and hit_bid:
            bought += s
        elif t["side"] == "BUY" and hit_ask:
            sold += s
    return min(bought, size), min(sold, size)


def step(st, now_ts):
    sel = {m["cid"]: m for m in st["markets"].values()}
    if not st["markets"]:
        for m in select_markets():
            st["markets"][m["cid"]] = {**m, "acct": {k: {"cash": 0.0, "inv": 0.0, "fee_eq": 0.0,
                                                          "fills": 0} for k in MODES}, "mid": None}
    for cid, m in list(st["markets"].items()):
        try:
            mid, tick = book_mid(m["tok"])
            if mid is None:
                continue
            trades = get(f"{DATA}/trades", market=cid, limit=500)
            new = [t for t in trades if int(t["timestamp"]) > st["last_ts"]]
            bid = round(round((m["mid"] if m["mid"] else mid) - OFFSET, 3), 3)
            ask = round((m["mid"] if m["mid"] else mid) + OFFSET, 3)
            size = m["min_size"]
            for mode in MODES:
                a = m["acct"][mode]
                b_, s_ = fills(mode, bid, ask, size, new, m["tok"])
                if a["inv"] >= INV_CAP:
                    b_ = 0.0
                if a["inv"] <= -INV_CAP:
                    s_ = 0.0
                a["cash"] += s_ * ask - b_ * bid
                a["inv"] += b_ - s_
                a["fills"] += (b_ > 0) + (s_ > 0)
                a["fee_eq"] += (b_ * bid * (1 - bid) + s_ * ask * (1 - ask)) * 0.05
            m["mid"] = mid
            m["pnl"] = {k: round(v["cash"] + v["inv"] * mid, 4) for k, v in m["acct"].items()}
            print(f"{m['q'][:45]:45} mid={mid:.3f} new_trades={len(new)} pnl={m['pnl']} "
                  f"inv={ {k: round(v['inv'],1) for k, v in m['acct'].items()} }")
        except Exception as e:
            print("market error", cid[:10], e)
    st["last_ts"] = now_ts
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                            "total": {k: round(sum(m.get("pnl", {}).get(k, 0) for m in st["markets"].values()), 4)
                                      for k in MODES},
                            "fee_eq": {k: round(sum(m["acct"][k]["fee_eq"] for m in st["markets"].values()), 4)
                                       for k in MODES},
                            "markets": {c[:10]: m.get("pnl") for c, m in st["markets"].items()}}) + "\n")


def main():
    try:
        st = json.load(open(STATE, encoding="utf-8"))
    except FileNotFoundError:
        st = {"started": datetime.now(timezone.utc).isoformat(), "last_ts": int(time.time()), "markets": {}}
    step(st, int(time.time()))
    json.dump(st, open(STATE, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
