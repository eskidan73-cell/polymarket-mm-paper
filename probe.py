"""Разведка публичных API Polymarket для бумажного маркет-мейкинга (ничего не торгует)."""
import json
import requests

GAMMA = "https://gamma-api.polymarket.com/markets"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"


def get(url, **params):
    r = requests.get(url, params=params, timeout=20)
    print(f"GET {r.url[:140]} -> {r.status_code}")
    return r.json()


ms = get(GAMMA, active="true", closed="false", limit=300, order="volume24hr", ascending="false")
print("markets:", len(ms))
print("keys:", sorted(ms[0].keys()))
rows = []
for m in ms:
    rows.append((m.get("rewardsMinSize"), m.get("rewardsMaxSpread"), m.get("volume24hr"),
                 m.get("liquidityNum"), m.get("spread"), m.get("question", "")[:60],
                 m.get("conditionId"), m.get("clobTokenIds"), m.get("endDate"),
                 (m.get("events") or [{}])[0].get("slug")))
rew = [r for r in rows if r[0]]
print("with rewards:", len(rew), "of", len(rows))
for r in rew[:12]:
    print(r[:6], r[8])

if rew:
    cid, toks = rew[0][6], json.loads(rew[0][7])
    print("--- book for", rew[0][5])
    b = get(f"{CLOB}/book", token_id=toks[0])
    print("book keys", list(b.keys()), "bids", b["bids"][:3], "asks", b["asks"][:3])
    print("--- trades by market")
    t = get(f"{DATA}/trades", market=cid, limit=10)
    print(type(t), (t[:2] if isinstance(t, list) else t))
