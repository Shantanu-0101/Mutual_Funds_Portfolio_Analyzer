"""Generate the dev and test-new question sets from templates (Phase R1, FR-R1.1 to FR-R1.5, FR-R1.7).

What the generator does, in order:

1. **Scheme split** (FR-R1.5). The 13 schemes of the 28 hand-written questions are test-only. Every
   other scheme of the month gets a category (equity / hybrid / debt / other, from its row counts) and,
   per category, a seeded shuffle sends ``DEV_SHARE`` of them to dev and the rest to test. So both sides
   get every kind of scheme, and a scheme (with its sections) is never on both sides.
2. **Questions per set.** The type mix is SPEC §6.6's (``TARGET_MIX``) scaled to the set size. Each
   type cycles through its templates (``templates.yaml``). A template's *picker* lists every valid slot
   choice from that side's schemes; the generator shuffles them (seeded) and takes the first one whose
   schemes have been used least so far, so questions spread over many schemes.
3. **Gold by code only.** Each candidate goes through ``src.eval.gold.compute``. A candidate is dropped
   when gold raises ``GoldError`` or (answerable types) has no gold rows. No gold value is written
   anywhere: the question files hold only ``gold_fn`` + ``params``, exactly like ``questions.yaml``.
4. **No leaks between sets.** An instrument (ISIN) used on one side is never used on the other: dev
   avoids the instruments of the 28 originals, test-new avoids dev's. A question that repeats an
   original's ``gold_fn`` + ``params`` is skipped.
5. **Names.** About a third of the questions (``SHORT_SHARE``, chosen by seeded sample) call a scheme
   by its short name ("the Flexi Cap Fund") instead of the full one (FR-R1.3). The choice, template,
   phrasing and gold sections go in each question's ``tags``.

Same seed + same data → byte-identical files.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import yaml

from src.eval.gold import EQUITY_SECTION, GoldError, compute, split_rating
from src.eval.questions import TARGET_MIX, Question
from src.retrieval.questions.sets import DEV_FILE, TEST_NEW_FILE, gold_sections, row_parent_map

TEMPLATES_FILE = Path(__file__).with_name("templates.yaml")
TYPE_ORDER = ("lookup", "aggregation", "debt", "cross_scheme", "unanswerable")
SET_SIZE = {"dev": 40, "test_new": 60}
ID_PREFIX = {"dev": "D", "test_new": "T"}
DEV_SHARE = 0.4
SHORT_SHARE = 1 / 3
AMC_PREFIX = "ADITYA BIRLA SUN LIFE "
FORMERLY = re.compile(r"\s*\(FORMERLY KNOWN AS ([^)]*)\)\s*$")

DEBT_SECTIONS = ("Debt Instruments", "Money Market Instruments")
LOOKUP_SECTIONS = (EQUITY_SECTION, *DEBT_SECTIONS, "Others")
SUBSECTIONS = ("Government Securities", "Securitised Debt", "Certificate of Deposits", "Commercial Paper",
               "STRIPS", "Treasury Bills")
RATING_GRADES = ("AAA", "AA+", "AA", "AA-", "A1+", "A+")
LIST_MAX_ROWS = 6            # a "list all holdings rated X" question names at most this many
MIN_GAP = 0.05               # which_holds_more: the two amounts differ by at least 5 % of the larger
TOP_N = (3, 5, 10)

ACRONYMS = {"ELSS", "MNC", "ESG", "PSU", "PSE", "BSE", "CRISIL", "IBX", "SDL", "AAA", "NBFC", "HFC", "ETF",
            "ETFS", "FOF", "US", "IT", "MSCI", "TQ"}
SMALL_WORDS = {"AND", "OF", "TO", "THE"}


# --------------------------------------------------------------------------- names

def _title_word(word: str, first: bool) -> str:
    if word in ACRONYMS:
        return word
    if re.fullmatch(r"\d+S", word):                 # 30S → 30s
        return word.lower()
    if any(c.isdigit() for c in word):
        return word
    if word in SMALL_WORDS and not first:
        return word.lower()
    return re.sub(r"[a-z]", lambda m: m.group().upper(), word.lower(), count=1)


def title_name(upper: str) -> str:
    """``LARGE & MID CAP FUND`` → ``Large & Mid Cap Fund``; acronyms (ETF, PSU, CRISIL-IBX) stay upper."""
    out = []
    for i, word in enumerate(upper.split()):
        parts = re.split(r"([-/])", word)
        first = i == 0 or out[-1] == "-"            # "RETIREMENT FUND - THE 30S PLAN" → "... - The 30s Plan"
        out.append("".join(p if p in "-/" else _title_word(p, first and j == 0) for j, p in enumerate(parts)))
    return " ".join(out)


def short_upper(scheme: str) -> str:
    """The current name without the AMC prefix and without the "(FORMERLY KNOWN AS …)" part."""
    name = FORMERLY.sub("", scheme.strip())
    return name[len(AMC_PREFIX):] if name.startswith(AMC_PREFIX) else name


def scheme_text(scheme: str, short: bool) -> str:
    base = title_name(short_upper(scheme))
    return f"the {base}" if short else f"Aditya Birla Sun Life {base}"


def option_alias(scheme: str) -> str:
    return title_name(short_upper(scheme))


def clean_instrument(name: str) -> str:
    """Drop the file's footnote markers (``**`` thinly traded, ``#`` unlisted, ...) from the end."""
    return re.sub(r"(\s*[*#^$@]+)+\s*$", "", str(name)).strip()


def month_text(as_of_date: str, rng: random.Random) -> str:
    d = pd.Timestamp(as_of_date)
    return f"{d.day} {d.strftime('%b') if rng.random() < 0.5 else d.strftime('%B')} {d.year}"


# --------------------------------------------------------------------------- scheme split

def scheme_stats(h: pd.DataFrame) -> pd.DataFrame:
    g = h.groupby("scheme_code")
    return pd.DataFrame({
        "scheme": g["scheme"].first(),
        "rows": g.size(),
        "equity": g["section"].agg(lambda s: int((s == EQUITY_SECTION).sum())),
        "debt_like": g["section"].agg(lambda s: int(s.isin(DEBT_SECTIONS).sum())),
    }).sort_index()


def category(equity: int, debt_like: int) -> str:
    if equity >= 5 and debt_like >= 5:
        return "hybrid"
    if equity >= 5:
        return "equity"
    if debt_like >= 1:
        return "debt"
    return "other"


def split_schemes(stats: pd.DataFrame, test_only: set[str], seed: int) -> dict[str, str]:
    """scheme code → ``"dev"`` or ``"test"``. ``test_only`` (the originals' schemes) always go to test."""
    rng = random.Random(f"{seed}:split")
    side = {c: "test" for c in sorted(test_only) if c in stats.index}
    cats = {c: category(r.equity, r.debt_like) for c, r in stats.iterrows() if c not in side}
    for cat in sorted(set(cats.values())):
        codes = sorted(c for c, k in cats.items() if k == cat)
        rng.shuffle(codes)
        n_dev = round(len(codes) * DEV_SHARE)
        side.update({c: "dev" for c in codes[:n_dev]})
        side.update({c: "test" for c in codes[n_dev:]})
    return dict(sorted(side.items()))


def scaled_mix(total: int) -> dict[str, int]:
    """TARGET_MIX scaled to ``total`` questions (largest remainder)."""
    base = sum(TARGET_MIX.values())
    exact = {t: TARGET_MIX[t] * total / base for t in TYPE_ORDER}
    mix = {t: int(v) for t, v in exact.items()}
    for t in sorted(TYPE_ORDER, key=lambda t: (-(exact[t] - mix[t]), TYPE_ORDER.index(t)))[: total - sum(mix.values())]:
        mix[t] += 1
    return mix


# --------------------------------------------------------------------------- candidates

@dataclass
class Candidate:
    params: dict[str, Any]
    slots: dict[str, Any]
    schemes: list[str]
    isins: list[str] = field(default_factory=list)


@dataclass
class Pool:
    """The holdings rows of one side's schemes, for one month."""
    h: pd.DataFrame
    month: str
    stats: pd.DataFrame

    @property
    def codes(self) -> list[str]:
        return list(self.stats.index)

    def scheme_name(self, code: str) -> str:
        return str(self.stats.loc[code, "scheme"])


def _unique_isin_rows(h: pd.DataFrame, sections: tuple[str, ...]) -> pd.DataFrame:
    """Rows usable as "the instrument" of a question: valid ISIN, a % and a value, listed once in the
    scheme, and not a unit of another ABSL fund (its name would put a third scheme name in the question)."""
    own_fund = h["instrument"].str.casefold().str.contains("aditya birla sun life", regex=False)
    rows = h[h["section"].isin(sections) & h["isin_valid"] & h["pct_nav"].notna() & (h["pct_nav"] > 0)
             & h["market_value_lakhs"].notna() & ~h["name_suspect"] & ~own_fund]
    dup = rows.duplicated(["scheme_code", "isin"], keep=False)
    return rows[~dup]


def pick_holding(pool: Pool, tpl: dict) -> list[Candidate]:
    rows = _unique_isin_rows(pool.h, LOOKUP_SECTIONS)
    return [Candidate({"scheme_code": r.scheme_code, "as_of_date": pool.month, "isin": r.isin},
                      {"instrument": clean_instrument(r.instrument)}, [r.scheme_code], [r.isin])
            for r in rows.itertuples()]


def _equity(pool: Pool) -> pd.DataFrame:
    return pool.h[pool.h["section"] == EQUITY_SECTION]


def pick_industry(pool: Pool, tpl: dict) -> list[Candidate]:
    eq = _equity(pool)
    out = []
    for (code, industry), n in eq.groupby(["scheme_code", "industry_or_rating"]).size().items():
        if n >= 2 and pool.stats.loc[code, "equity"] >= 10:
            out.append(Candidate({"scheme_code": code, "as_of_date": pool.month, "industry": industry},
                                 {"industry": industry}, [code]))
    return out


def pick_top_n(pool: Pool, tpl: dict) -> list[Candidate]:
    return [Candidate({"scheme_code": c, "as_of_date": pool.month, "n": n}, {"n": n}, [c])
            for c in pool.codes if pool.stats.loc[c, "equity"] >= 15 for n in TOP_N]


def pick_equity_scheme(pool: Pool, tpl: dict) -> list[Candidate]:
    return [Candidate({"scheme_code": c, "as_of_date": pool.month}, {}, [c])
            for c in pool.codes if pool.stats.loc[c, "equity"] >= 5]


def pick_hybrid_equity_section(pool: Pool, tpl: dict) -> list[Candidate]:
    return [Candidate({"scheme_code": c, "as_of_date": pool.month, "section": EQUITY_SECTION}, {}, [c])
            for c in pool.codes
            if category(pool.stats.loc[c, "equity"], pool.stats.loc[c, "debt_like"]) == "hybrid"]


def _rated(pool: Pool) -> pd.DataFrame:
    rows = pool.h[pool.h["section"] != EQUITY_SECTION]
    parts = rows["industry_or_rating"].map(split_rating)
    return rows.assign(_agency=parts.map(lambda p: p[0]), _grade=parts.map(lambda p: p[1]))


def pick_rating_grade(pool: Pool, tpl: dict) -> list[Candidate]:
    rated = _rated(pool)
    rated = rated[rated["_agency"].notna() & rated["_grade"].isin(RATING_GRADES)]
    out = []
    for code, grade in sorted(set(zip(rated["scheme_code"], rated["_grade"]))):
        note = "; not counting securitised AAA(SO) ratings" if grade == "AAA" else ""
        out.append(Candidate({"scheme_code": code, "as_of_date": pool.month, "rating": grade},
                             {"rating": grade, "so_note": note}, [code]))
    return out


def pick_agency_rating(pool: Pool, tpl: dict) -> list[Candidate]:
    rated = _rated(pool)
    rated = rated[rated["_agency"].notna()]
    rating = rated["_agency"] + " " + rated["_grade"]
    out = []
    for (code, r), n in rated.assign(_rating=rating).groupby(["scheme_code", "_rating"]).size().items():
        if 1 <= n <= LIST_MAX_ROWS:
            out.append(Candidate({"scheme_code": code, "as_of_date": pool.month, "rating": r}, {"rating": r}, [code]))
    return out


def pick_debt_subsection(pool: Pool, tpl: dict) -> list[Candidate]:
    rows = pool.h[pool.h["section"].isin(DEBT_SECTIONS) & pool.h["subsection"].isin(SUBSECTIONS)]
    keys = sorted(set(zip(rows["scheme_code"], rows["section"], rows["subsection"])))
    return [Candidate({"scheme_code": c, "as_of_date": pool.month, "section": s, "subsection": sub},
                      {"section": s, "subsection": sub}, [c]) for c, s, sub in keys]


def _aliases_clash(a: str, b: str) -> bool:
    """True if one option name is a whole-word part of the other (choice scoring could not tell them apart)."""
    na, nb = f" {a.casefold()} ", f" {b.casefold()} "
    return na in nb or nb in na


def pick_shared_holding(pool: Pool, tpl: dict) -> list[Candidate]:
    col = "pct_nav" if tpl["measure"] == "pct" else "market_value_lakhs"
    rows = _unique_isin_rows(pool.h, LOOKUP_SECTIONS)
    out = []
    for isin, grp in rows.groupby("isin", sort=True):
        held = grp.sort_values("scheme_code")
        for a, b in combinations(held.itertuples(), 2):
            va, vb = getattr(a, col), getattr(b, col)
            if abs(va - vb) < MIN_GAP * max(va, vb):
                continue
            if _aliases_clash(option_alias(a.scheme), option_alias(b.scheme)):
                continue
            out.append(Candidate(
                {"schemes": [a.scheme_code, b.scheme_code], "as_of_date": pool.month, "isin": isin,
                 "measure": tpl["measure"]},
                {"instrument": clean_instrument(a.instrument)}, [a.scheme_code, b.scheme_code], [isin]))
    return out


def pick_overlap_pair(pool: Pool, tpl: dict) -> list[Candidate]:
    eq = _equity(pool)
    keys = {c: set(g["isin"][g["isin_valid"]]) for c, g in eq.groupby("scheme_code")
            if pool.stats.loc[c, "equity"] >= 10}
    return [Candidate({"schemes": [a, b], "as_of_date": pool.month}, {}, [a, b])
            for a, b in combinations(sorted(keys), 2) if keys[a] & keys[b]
            and not _aliases_clash(option_alias(pool.scheme_name(a)), option_alias(pool.scheme_name(b)))]


def pick_any_scheme(pool: Pool, tpl: dict) -> list[Candidate]:
    return [Candidate({}, {}, [c]) for c in pool.codes]


PICKERS: dict[str, Callable[[Pool, dict], list[Candidate]]] = {
    f.__name__: f for f in (pick_holding, pick_industry, pick_top_n, pick_equity_scheme,
                            pick_hybrid_equity_section, pick_rating_grade, pick_agency_rating,
                            pick_debt_subsection, pick_shared_holding, pick_overlap_pair, pick_any_scheme)
}


# --------------------------------------------------------------------------- generation

def load_templates(path: Path = TEMPLATES_FILE) -> dict[str, list[dict]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for qtype, tpls in raw.items():
        if qtype not in TYPE_ORDER:
            raise ValueError(f"templates.yaml: unknown type {qtype!r}")
        for t in tpls:
            if t["picker"] not in PICKERS:
                raise ValueError(f"templates.yaml: {t['id']}: unknown picker {t['picker']!r}")
    return raw


def _key(gold_fn: str, params: dict) -> str:
    return gold_fn + json.dumps(params, sort_keys=True)


@dataclass
class SetBuilder:
    name: str
    pool: Pool
    holdings: pd.DataFrame
    row_parent: dict
    rng: random.Random
    banned_isins: set[str]
    used_keys: set[str]
    usage: Counter = field(default_factory=Counter)
    isins: set[str] = field(default_factory=set)
    _candidates: dict[str, list[Candidate]] = field(default_factory=dict)

    def candidates(self, tpl: dict) -> list[Candidate]:
        tid = tpl["id"]
        if tid not in self._candidates:
            cands = PICKERS[tpl["picker"]](self.pool, tpl)
            self.rng.shuffle(cands)
            self._candidates[tid] = cands
        return self._candidates[tid]

    def build(self, qtype: str, tpl: dict, short: bool) -> dict:
        cands = sorted(self.candidates(tpl), key=lambda c: sum(self.usage[s] for s in c.schemes))  # stable
        taken = self.banned_isins | self.isins
        for c in cands:
            if taken.intersection(c.isins):
                continue
            phrasing = self.rng.randrange(len(tpl["phrasings"]))
            key = _key(tpl["gold_fn"], c.params) + (f"#{c.schemes[0]}#{phrasing}" if not c.params else "")
            if key in self.used_keys:
                continue
            q = self._question(qtype, tpl, c, phrasing, short)
            if q is None:
                continue
            self.used_keys.add(key)
            self.usage.update(c.schemes)
            self.isins.update(c.isins)
            return q
        raise RuntimeError(f"{self.name}: no usable candidate left for template {tpl['id']}")

    def _question(self, qtype: str, tpl: dict, c: Candidate, phrasing: int, short: bool) -> dict | None:
        params = dict(c.params)
        if "schemes" in params and self.rng.random() < 0.5:
            params["schemes"] = list(reversed(params["schemes"]))
        try:
            gold = compute(self.holdings, tpl["gold_fn"], params)
        except GoldError:
            return None
        answerable = tpl["answer_kind"] != "not_in_data"
        if answerable and not gold.rows:
            return None
        schemes = params.get("schemes") or c.schemes
        names = [scheme_text(self.pool.scheme_name(s), short) for s in schemes]
        slots = {**c.slots, "scheme": names[0], "month": month_text(self.pool.month, self.rng)}
        if len(names) > 1:
            slots["scheme_b"] = names[1]
        text = tpl["phrasings"][phrasing].format(**slots)
        text = text[0].upper() + text[1:]
        q: dict[str, Any] = {"id": "", "type": qtype, "text": text, "answer_kind": tpl["answer_kind"]}
        if tpl.get("unit"):
            q["unit"] = tpl["unit"]
        if tpl["answer_kind"] == "choice":
            q["options"] = {s: [option_alias(self.pool.scheme_name(s))] for s in schemes}
        q["gold_fn"] = tpl["gold_fn"]
        q["params"] = params
        q["tags"] = {
            "template": tpl["id"], "phrasing": phrasing + 1, "short_name": short,
            "schemes": list(schemes),
            "gold_sections": gold_sections(Question(id="?", type=qtype, text=text, answer_kind=tpl["answer_kind"],
                                                    gold_fn=tpl["gold_fn"], params=params),
                                           self.holdings, self.row_parent) if answerable else [],
        }
        return q


def plan_templates(templates: dict[str, list[dict]], mix: dict[str, int]) -> list[tuple[str, dict]]:
    """Which template each question uses: per type, templates in turn (file order)."""
    plan = []
    for qtype in TYPE_ORDER:
        tpls = templates[qtype]
        plan += [(qtype, tpls[i % len(tpls)]) for i in range(mix[qtype])]
    return plan


@dataclass
class Generated:
    sets: dict[str, list[dict]]
    split: dict[str, str]
    categories: dict[str, str]


def generate(holdings: pd.DataFrame, parents: pd.DataFrame, originals: list[Question], month: str,
             seed: int, templates: dict[str, list[dict]] | None = None,
             sizes: dict[str, int] | None = None) -> Generated:
    templates = templates or load_templates()
    sizes = sizes or SET_SIZE
    h = holdings[holdings["as_of_date"].astype(str) == month]
    stats = scheme_stats(h)
    test_only = {s for q in originals for s in ([q.params["scheme_code"]] if "scheme_code" in q.params
                                                 else q.params.get("schemes", []))}
    split = split_schemes(stats, test_only, seed)
    row_parent = row_parent_map(parents)
    original_isins = {q.params["isin"] for q in originals if q.params.get("isin")}
    used_keys = {_key(q.gold_fn, q.params) for q in originals if q.answerable}

    sets: dict[str, list[dict]] = {}
    banned = set(original_isins)
    for name, side in (("dev", "dev"), ("test_new", "test")):
        codes = [c for c, s in split.items() if s == side]
        pool = Pool(h[h["scheme_code"].isin(codes)], month, stats.loc[codes])
        rng = random.Random(f"{seed}:{name}")
        plan = plan_templates(templates, scaled_mix(sizes[name]))
        short_ids = set(rng.sample(range(len(plan)), round(len(plan) * SHORT_SHARE)))
        b = SetBuilder(name, pool, h, row_parent, rng, banned_isins=set(banned), used_keys=used_keys)
        qs = [b.build(qtype, tpl, i in short_ids) for i, (qtype, tpl) in enumerate(plan)]
        for i, q in enumerate(qs, 1):
            q["id"] = f"{ID_PREFIX[name]}{i:03d}"
        sets[name] = qs
        banned |= b.isins                      # test-new never reuses an instrument dev used
    cats = {c: category(r.equity, r.debt_like) for c, r in stats.iterrows()}
    return Generated(sets, split, cats)


# --------------------------------------------------------------------------- writing

HEADER = """# {title} for the retrieval benchmark (Phase R1). WRITTEN BY CODE, do not edit by hand:
# regenerate with `python -m src.retrieval questions` (seed {seed}, month {month}).
# Gold answers are computed at run time by src/eval/gold.py from gold_fn + params, never stored here.
# tags: template / phrasing (1-based) / short_name (scheme called by its short name) / schemes /
#       gold_sections (parent ids of the hierarchical chunker that hold the gold rows, FR-R1.7).
"""

TITLES = {"dev": "Dev questions (used only to choose settings)",
          "test_new": "New test questions (scored together with src/eval/questions.yaml)"}


def to_yaml(questions: list[dict], name: str, seed: int, month: str) -> str:
    body = yaml.safe_dump(questions, sort_keys=False, allow_unicode=True, width=10_000, default_flow_style=None)
    body = re.sub(r"^- id:", "\n- id:", body, flags=re.M).lstrip("\n")
    return HEADER.format(title=TITLES[name], seed=seed, month=month) + "\n" + body


def write_sets(gen: Generated, seed: int, month: str,
               files: dict[str, Path] | None = None) -> dict[str, Path]:
    files = files or {"dev": DEV_FILE, "test_new": TEST_NEW_FILE}
    for name, path in files.items():
        path.write_text(to_yaml(gen.sets[name], name, seed, month), encoding="utf-8", newline="\n")
    return files
