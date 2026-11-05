"""Elo modeli asosidagi ehtimollar (api/_elo.py dagi reytinglardan, kredit sarflamaydi)."""
import difflib
import math
import re
import unicodedata

# football-data.co.uk nomi -> The Odds API nomiga yaqin shakl
ALIASES = {
    "man city": "manchester city", "man united": "manchester united", "nott'm forest": "nottingham forest",
    "wolves": "wolverhampton wanderers", "spurs": "tottenham hotspur", "brighton": "brighton and hove albion",
    "ath bilbao": "athletic bilbao", "ath madrid": "atletico madrid", "betis": "real betis",
    "sociedad": "real sociedad", "celta": "celta vigo", "vallecano": "rayo vallecano", "espanol": "espanyol",
    "la coruna": "deportivo la coruna", "oviedo": "real oviedo", "valladolid": "real valladolid",
    "milan": "ac milan", "inter": "inter milan", "roma": "as roma", "verona": "hellas verona",
    "dortmund": "borussia dortmund", "m'gladbach": "borussia monchengladbach", "leverkusen": "bayer leverkusen",
    "ein frankfurt": "eintracht frankfurt", "mainz": "mainz 05", "fc koln": "koln", "st pauli": "st pauli",
    "hamburg": "hamburger sv", "paris sg": "paris saint germain", "st etienne": "saint etienne",
    "bayern munich": "bayern munich",
}
DROP = {"fc", "cf", "afc", "ac", "as", "ss", "sc", "cd", "ud", "rcd", "sd", "ca", "vfb", "vfl", "tsg",
        "fsv", "sv", "bv", "1", "club", "calcio", "de", "the", "and", "05"}


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = ALIASES.get(s.strip(), s)
    s = re.sub(r"[^a-z0-9 ]", " ", s.replace("&", " and "))
    return " ".join(t for t in s.split() if t not in DROP)


def resolve(name, teams):
    """The Odds API nomini Elo jadvalidagi nomga moslaydi."""
    n = norm(name)
    table = {norm(t): t for t in teams}
    if n in table:
        return table[n]
    nt = set(n.split())
    for k, t in table.items():
        kt = set(k.split())
        if kt and (kt <= nt or nt <= kt):
            return t
    m = difflib.get_close_matches(n, list(table), n=1, cutoff=0.6)
    return table[m[0]] if m else None


def load():
    try:
        from _elo import ELO
        return ELO
    except Exception:
        return {}


def ordered_logit(x, H, s, c):
    z = (x + H) / s
    ph = 1 / (1 + math.exp(-(z - c)))
    pa = 1 / (1 + math.exp(z + c))
    pd = max(1 - ph - pa, 0.01)
    t = ph + pd + pa
    return [ph / t, pd / t, pa / t]


def elo_info(league, home, away, elo=None):
    """{'p': [1, X, 2], 'rh', 'ra', 'fh', 'fa', 'h', 'a'} yoki None."""
    elo = elo if elo is not None else load()
    L = (elo.get("leagues") or {}).get(league)
    if not L:
        return None
    h, a = resolve(home, L["ratings"]), resolve(away, L["ratings"])
    if not h or not a or h == a:
        return None
    rh, ra = L["ratings"][h], L["ratings"][a]
    return {"p": ordered_logit(rh - ra, L["H"], L["s"], L["c"]), "rh": rh, "ra": ra, "w": L.get("w", 0.5),
            "fh": L["form"].get(h, ""), "fa": L["form"].get(a, ""), "h": h, "a": a}


def blend(pe, pm, w):
    """Model (pe) va bozor (pm) ehtimollarini tarixda eng yaxshi chiqqan vaznda aralashtiradi."""
    if pe and pm:
        q = [w * pe[i] + (1 - w) * pm[i] for i in range(len(pm))]
        t = sum(q)
        return [x / t for x in q]
    return pe or pm
