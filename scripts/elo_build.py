"""Elo modeli: football-data.co.uk natijalaridan jamoalar reytingini hisoblaydi (GitHub Actions, kunlik).

Natija: api/_elo.py (bot va kuzatuv shu fayldan foydalanadi). API kredit sarflanmaydi.
"""
import csv
import io
import math
import os
import pprint
from datetime import datetime, timezone

import requests

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "api", "_elo.py")

DIVS = {"soccer_epl": "E0", "soccer_spain_la_liga": "SP1", "soccer_italy_serie_a": "I1",
        "soccer_germany_bundesliga": "D1", "soccer_france_ligue_one": "F1"}
K, HFA_UPDATE, NEW_TEAM, REGRESS = 20, 60, 1440, 0.2


def seasons(now=None):
    now = now or datetime.now(timezone.utc)
    y = now.year % 100 if now.month >= 7 else now.year % 100 - 1  # mavsum iyul-avgustda boshlanadi
    return [f"{(y - i) % 100:02d}{(y - i + 1) % 100:02d}" for i in (2, 1, 0)]


def load(div, season):
    url = f"https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return []
        text = r.content.decode("utf-8-sig", errors="replace")
    except Exception:
        return []
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            d = row["Date"].strip()
            dt = datetime.strptime(d, "%d/%m/%Y" if len(d) > 8 else "%d/%m/%y")
            hg, ag = int(row["FTHG"]), int(row["FTAG"])
        except Exception:
            continue

        def odd(k):
            try:
                return float(row.get(k) or 0) or None
            except ValueError:
                return None
        mkt = [odd("AvgH"), odd("AvgD"), odd("AvgA")]
        rows.append({"d": dt, "h": row["HomeTeam"].strip(), "a": row["AwayTeam"].strip(),
                     "hg": hg, "ag": ag, "season": season, "mkt": mkt if all(mkt) else None})
    return rows


def probs(x, H, s, c):
    """Tartiblangan logit: x = reytinglar farqi (uy - mehmon)."""
    z = (x + H) / s
    ph = 1 / (1 + math.exp(-(z - c)))
    pa = 1 / (1 + math.exp(z + c))
    return [ph, max(1 - ph - pa, 0.01), pa]


def margin_mult(gd):
    gd = abs(gd)
    return 1 if gd <= 1 else (1.5 if gd == 2 else (11 + gd) / 8)


def build_league(matches):
    matches.sort(key=lambda m: m["d"])
    R, form, first_season = {}, {}, matches[0]["season"] if matches else None
    cur, hist = None, []
    for m in matches:
        if m["season"] != cur:
            if cur is not None:  # yangi mavsum: reytinglar o'rtachaga biroz qaytadi
                for t in R:
                    R[t] = 1500 + (R[t] - 1500) * (1 - REGRESS)
            cur = m["season"]
        for t in (m["h"], m["a"]):
            if t not in R:
                R[t] = 1500 if m["season"] == first_season else NEW_TEAM
        x = R[m["h"]] - R[m["a"]]
        res = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
        if m["season"] != first_season:
            hist.append((x, res, m["mkt"]))
        exp_h = 1 / (1 + 10 ** (-(x + HFA_UPDATE) / 400))
        score = 1 if res == 0 else (0.5 if res == 1 else 0)
        delta = K * margin_mult(m["hg"] - m["ag"]) * (score - exp_h)
        R[m["h"]] += delta
        R[m["a"]] -= delta
        for t, r in ((m["h"], "✅" if res == 0 else ("➖" if res == 1 else "❌")),
                     (m["a"], "✅" if res == 2 else ("➖" if res == 1 else "❌"))):
            form[t] = (form.get(t, "") + r)[-5:]
    return R, form, hist


def fit(hist):
    """H, s, c parametrlarini tarixiy o'yinlarda log-loss bo'yicha tanlaydi."""
    best = (9e9, 60, 250, 0.45)
    for H in range(0, 130, 10):
        for s in range(120, 420, 20):
            for c10 in range(10, 100, 5):
                c = c10 / 100
                ll = 0.0
                for x, res, _ in hist:
                    ll -= math.log(max(probs(x, H, s, c)[res], 1e-9))
                if ll < best[0]:
                    best = (ll, H, s, c)
    return best[1], best[2], best[3]


def evaluate(hist, H, s, c):
    n = ll_e = ll_m = acc_e = acc_m = 0
    for x, res, mkt in hist:
        if not mkt:
            continue
        pe = probs(x, H, s, c)
        inv = [1 / o for o in mkt]
        pm = [v / sum(inv) for v in inv]
        n += 1
        ll_e -= math.log(max(pe[res], 1e-9))
        ll_m -= math.log(max(pm[res], 1e-9))
        acc_e += max(range(3), key=lambda i: pe[i]) == res
        acc_m += max(range(3), key=lambda i: pm[i]) == res
    if not n:
        return {}
    return {"n": n, "ll_elo": round(ll_e / n, 4), "ll_mkt": round(ll_m / n, 4),
            "acc_elo": round(acc_e / n, 3), "acc_mkt": round(acc_m / n, 3)}


def main():
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "leagues": {}}
    ss = seasons()
    for lg, div in DIVS.items():
        matches = [m for s in ss for m in load(div, s)]
        if len(matches) < 200:
            print(f"{lg}: ma'lumot yetarli emas ({len(matches)})")
            continue
        R, form, hist = build_league(matches)
        H, s, c = fit(hist)
        ev = evaluate(hist, H, s, c)
        current = {m["h"] for m in matches if m["season"] == ss[-1]} | \
                  {m["a"] for m in matches if m["season"] == ss[-1]}
        out["leagues"][lg] = {
            "H": H, "s": s, "c": c, "eval": ev,
            "ratings": {t: round(R[t]) for t in sorted(current, key=lambda t: -R[t])},
            "form": {t: form.get(t, "") for t in current},
        }
        top = list(out["leagues"][lg]["ratings"].items())[:3]
        print(f"{lg}: {len(matches)} o'yin, H={H} s={s} c={c}, baho={ev}, top={top}")
    with open(OUT, "w") as f:
        f.write("# Avtomatik yaratiladi (scripts/elo_build.py). Qo'lda o'zgartirmang.\n")
        f.write("ELO = " + pprint.pformat(out, width=110, sort_dicts=False) + "\n")


if __name__ == "__main__":
    main()
