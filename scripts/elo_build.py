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
        hxg, axg = odd("HxG"), odd("AxG")
        rows.append({"d": dt, "h": row["HomeTeam"].strip(), "a": row["AwayTeam"].strip(),
                     "hg": hg, "ag": ag, "season": season, "mkt": mkt if all(mkt) else None,
                     "xg": (hxg or 0.0, axg or 0.0) if (hxg is not None or axg is not None) else None})
    return rows


def probs(x, H, s, c):
    """Tartiblangan logit: x = reytinglar farqi (uy - mehmon)."""
    z = (x + H) / s
    ph = 1 / (1 + math.exp(-(z - c)))
    pa = 1 / (1 + math.exp(z + c))
    return [ph, max(1 - ph - pa, 0.01), pa]


def pois(k, lam):
    return lam ** k * math.exp(-lam) / math.factorial(k)


def xg_score(hxg, axg):
    """xG bo'yicha 'adolatli natija': P(uy yutadi) + 0.5 * P(durang)."""
    ph = pd = 0.0
    for i in range(11):
        for j in range(11):
            q = pois(i, max(hxg, 0.05)) * pois(j, max(axg, 0.05))
            if i > j:
                ph += q
            elif i == j:
                pd += q
    return ph + 0.5 * pd


def margin_mult(gd):
    gd = abs(gd)
    return 1 if gd <= 1 else (1.5 if gd == 2 else (11 + gd) / 8)


def build_league(matches, alpha=1.0):
    """alpha — haqiqiy natija ulushi; (1 - alpha) — xG bo'yicha natija (xG bor o'yinlarda)."""
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
            hist.append((x, res, m["mkt"], m["season"]))
        exp_h = 1 / (1 + 10 ** (-(x + HFA_UPDATE) / 400))
        score = 1 if res == 0 else (0.5 if res == 1 else 0)
        gd = m["hg"] - m["ag"]
        if m.get("xg") and alpha < 1:
            score = alpha * score + (1 - alpha) * xg_score(*m["xg"])
            gd = alpha * gd + (1 - alpha) * (m["xg"][0] - m["xg"][1])
        delta = K * margin_mult(round(gd)) * (score - exp_h)
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
                for x, res, *_ in hist:
                    ll -= math.log(max(probs(x, H, s, c)[res], 1e-9))
                if ll < best[0]:
                    best = (ll, H, s, c)
    return best[1], best[2], best[3]


def mkt_probs(mkt):
    inv = [1 / o for o in mkt]
    return [v / sum(inv) for v in inv]


def best_weight(hist, H, s, c):
    """Model va bozorni aralashtirishning eng yaxshi vazni (model ulushi) — log-loss bo'yicha."""
    rows = [(probs(x, H, s, c), mkt_probs(mkt), res) for x, res, mkt, *_ in hist if mkt]
    if not rows:
        return 0.5, None
    best = (9e9, 0.5)
    for w100 in range(0, 105, 5):
        w = w100 / 100
        ll = -sum(math.log(max(w * pe[r] + (1 - w) * pm[r], 1e-9)) for pe, pm, r in rows)
        if ll < best[0]:
            best = (ll, w)
    return best[1], round(best[0] / len(rows), 4)


def season_ll(hist, H, s, c, season):
    rows = [(x, r) for x, r, mkt, ss in hist if ss == season]
    if not rows:
        return None, 0
    return sum(-math.log(max(probs(x, H, s, c)[r], 1e-9)) for x, r in rows), len(rows)


def evaluate(hist, H, s, c):
    n = ll_e = ll_m = acc_e = acc_m = 0
    for x, res, mkt, *_ in hist:
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
    data = {}
    for lg, div in DIVS.items():
        matches = [m for s in ss for m in load(div, s)]
        if len(matches) < 200:
            print(f"{lg}: ma'lumot yetarli emas ({len(matches)})")
            continue
        data[lg] = matches
    # 1) Har liga uchun H, s, c — faqat natijalar bilan (alpha=1)
    params = {}
    for lg, matches in data.items():
        _, _, hist = build_league(list(matches), 1.0)
        params[lg] = fit(hist)
    # 2) xG ulushini tanlash: joriy mavsum o'yinlarida (barcha ligalar birga) log-loss bo'yicha
    alpha_ll = {}
    for a10 in (10, 8, 6, 4, 2):
        alpha = a10 / 10
        tot, n = 0.0, 0
        for lg, matches in data.items():
            _, _, hist = build_league(list(matches), alpha)
            ll, k = season_ll(hist, *params[lg], ss[-1])
            if ll is not None:
                tot, n = tot + ll, n + k
        alpha_ll[alpha] = round(tot / n, 4) if n else None
    valid = {a: v for a, v in alpha_ll.items() if v is not None}
    alpha = min(valid, key=valid.get) if valid else 1.0
    print(f"xG ulushi tanlovi (joriy mavsum log-loss): {alpha_ll} -> natija ulushi {alpha}")
    out["alpha"] = alpha
    out["alpha_ll"] = alpha_ll
    # 3) Yakuniy reytinglar, aralashtirish vazni va baho
    for lg, matches in data.items():
        R, form, hist = build_league(list(matches), alpha)
        H, s, c = params[lg]
        ev = evaluate(hist, H, s, c)
        w, ll_b = best_weight(hist, H, s, c)
        ev["w"], ev["ll_blend"] = w, ll_b
        cur = ss[-1]
        current = {m["h"] for m in matches if m["season"] == cur} | {m["a"] for m in matches if m["season"] == cur}
        out["leagues"][lg] = {
            "H": H, "s": s, "c": c, "w": w, "eval": ev,
            "ratings": {t: round(R[t]) for t in sorted(current, key=lambda t: -R[t])},
            "form": {t: form.get(t, "") for t in current},
        }
        top = list(out["leagues"][lg]["ratings"].items())[:3]
        print(f"{lg}: {len(matches)} o'yin, H={H} s={s} c={c}, model vazni={w}, baho={ev}, top={top}")
    with open(OUT, "w") as f:
        f.write("# Avtomatik yaratiladi (scripts/elo_build.py). Qo'lda o'zgartirmang.\n")
        f.write("ELO = " + pprint.pformat(out, width=110, sort_dicts=False) + "\n")


if __name__ == "__main__":
    main()
