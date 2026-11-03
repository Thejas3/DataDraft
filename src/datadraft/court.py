"""The court (§6): an evidence bundle, one structured Claude call, and a citation
validator. The verdict and numbers are already decided; the court only argues them.

D8: the prompt names teams only as "your team" / "roster N" and players by canonical
name, so no leaguemate-written text reaches the model.
D21: the model writes every number as an {E#} placeholder, rendered from the bundle
afterwards. A bare digit in prose (outside WR2-style ranks) fails validation."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from .delta import Side, TradeDelta, player_name
from .projections import cell

MODEL = os.environ.get("DATADRAFT_MODEL", "claude-opus-5-5")
MAX_CALLS = 3  # one call plus up to 2 regenerations
PLACEHOLDER = re.compile(r"\{(E\d+)\}")
WHITELIST = re.compile(r"\b(?:QB|RB|WR|TE|K|DEF|FLEX)\d{1,2}\b|\b\d-for-\d\b")
WITHHELD = "Some arguments were withheld because they could not be sourced."

SCHEMA = {
    "type": "object",
    "properties": {
        k: {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"},
                           "evidence_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "evidence_ids"],
            "additionalProperties": False}}
        for k in ("for", "against", "rationale")
    },
    "required": ["for", "against", "rationale"],
    "additionalProperties": False,
}

SYSTEM = """You argue a fantasy football trade ruling that has already been decided by a \
deterministic engine. You never change the verdict and never invent facts.

Rules:
- Each item is ONE sentence and lists the evidence ids it relies on in evidence_ids.
- Write every number (points, weeks, counts, deltas) ONLY as a placeholder like {E3}; \
it will be replaced by the bundle value. Never type digits yourself, except position \
ranks such as WR2 or RB1.
- Use only evidence ids that appear in the bundle.
- Never generalize across weeks ("every week", "all weeks", "never") unless the \
weeks-with-a-gain or weeks-with-a-loss evidence shows it, and cite that evidence.
- "for" = reasons to make the trade, "against" = reasons not to, "rationale" = one to \
three sentences explaining why the verdict follows.
- Two to four items each for "for" and "against". Plain, direct sentences."""


@dataclass
class Argument:
    text: str
    evidence_ids: list


@dataclass
class CourtResult:
    arguments: dict = field(default_factory=dict)  # section -> [Argument]
    notice: str = ""
    calls: int = 0


# ---- evidence bundle ---------------------------------------------------------------

def _fmt(x: float) -> str:
    return f"{x:+.1f}" if isinstance(x, float) else str(x)


def bundle(snap, matrix, ruling) -> list[dict]:
    d: TradeDelta = ruling.delta
    items: list[dict] = []

    def add(label: str, value) -> str:
        eid = f"E{len(items) + 1}"
        items.append({"id": eid, "label": label, "value": value})
        return eid

    weeks = d.weeks
    add("verdict (fixed)", ruling.verdict)
    add("your lineup change, pts/week over the horizon", _fmt(d.me.delta))
    add("their lineup change, pts/week over the horizon", _fmt(d.them.delta))
    add("verdict band, pts/week", f"{ruling.band:.1f}")
    add("first week counted", f"week {weeks[0]}")
    add("last week counted (final playoff week)", f"week {weeks[-1]}")
    add("weeks counted", str(len(weeks)))
    for label, side_pids, side in (("you send", d.trade.give, d.me),
                                   ("you receive", d.trade.get, d.me)):
        for pid in side_pids:
            name = player_name(snap.players, pid)
            avg = sum(cell(matrix, w, pid).points for w in weeks) / len(weeks)
            add(f"{name} ({label}): projected pts/week", f"{avg:.1f}")
            slot = side.lineup_after.get(pid) if label == "you receive" else \
                side.lineup_before.get(pid)
            where = "your" if label == "you receive" else "your current"
            add(f"{name}: slot in {where} week-{weeks[0]} lineup", slot or "bench")
    for who, side in (("you", d.me), ("they", d.them)):
        for pid in side.forced_drops:
            add(f"forced drop ({who}, roster limit)", player_name(snap.players, pid))
    per_week = d.me.per_week
    best = max(per_week.items(), key=lambda kv: kv[1])
    worst = min(per_week.items(), key=lambda kv: kv[1])
    if best[1] > 0:  # a "best week" of zero or less is no argument for the trade
        add("your best week for this trade", f"week {best[0]}: {_fmt(best[1])} pts")
    if worst[1] < 0:
        add("your worst week for this trade", f"week {worst[0]}: {_fmt(worst[1])} pts")
    for label, n in (("gain", sum(v > 0 for v in per_week.values())),
                     ("loss", sum(v < 0 for v in per_week.values()))):
        add(f"weeks where your lineup shows a {label}", f"{n} of {len(weeks)}")
    if ruling.counter:
        c = ruling.counter
        add("counteroffer: you send", ", ".join(player_name(snap.players, p) for p in c.trade.give))
        add("counteroffer: you receive", ", ".join(player_name(snap.players, p) for p in c.trade.get))
        add("counteroffer: your change, pts/week", _fmt(c.me.delta))
        add("counteroffer: their change, pts/week", _fmt(c.them.delta))
    for n in ruling.notes:
        add("caveat", n)
    return items


# ---- validator ---------------------------------------------------------------------

def validate(raw: dict, ids: set) -> tuple[dict, list]:
    """Return (passing arguments by section, error strings for the failing ones)."""
    ok, errors = {}, []
    for section in ("for", "against", "rationale"):
        ok[section] = []
        for i, item in enumerate(raw.get(section) or []):
            text = str(item.get("text", "")).strip()
            cited = [str(e) for e in item.get("evidence_ids") or []]
            where = f"{section}[{i}]"
            used = PLACEHOLDER.findall(text)
            bad = sorted({e for e in cited + used if e not in ids})
            prose = WHITELIST.sub("", PLACEHOLDER.sub("", text))
            if not text:
                errors.append(f"{where}: empty sentence")
            elif not cited:
                errors.append(f"{where}: no evidence_ids")
            elif bad:
                errors.append(f"{where}: unknown evidence ids {', '.join(bad)}")
            elif re.search(r"\d", prose):
                errors.append(f"{where}: bare number in text; use {{E#}} placeholders")
            elif len(re.findall(r"[.!?](?:\s|$)", text)) > 1:
                errors.append(f"{where}: more than one sentence")
            else:
                ok[section].append(Argument(text, sorted(set(cited) | set(used))))
    return ok, errors


def render(text: str, items: list[dict]) -> str:
    values = {i["id"]: str(i["value"]) for i in items}
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


# ---- the call ----------------------------------------------------------------------

def _prompt(snap, ruling, items) -> str:
    d = ruling.delta
    return (
        f"Trade: your team sends {', '.join(player_name(snap.players, p) for p in d.trade.give)} "
        f"to roster {d.trade.them} for "
        f"{', '.join(player_name(snap.players, p) for p in d.trade.get)}.\n"
        f"Verdict: {ruling.verdict}.\n\nEvidence bundle:\n"
        + json.dumps(items, indent=1)
    )


def argue(snap, matrix, ruling, client=None) -> CourtResult:
    items = bundle(snap, matrix, ruling)
    ids = {i["id"] for i in items}
    if client is None:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return CourtResult(notice="Court arguments skipped: set ANTHROPIC_API_KEY to "
                                      "enable them. The ruling and numbers are unaffected.")
        import anthropic
        client = anthropic.Anthropic()
    messages = [{"role": "user", "content": _prompt(snap, ruling, items)}]
    result = CourtResult()
    passed: dict = {}
    for attempt in range(MAX_CALLS):
        result.calls += 1
        try:
            resp = client.messages.create(
                model=MODEL, max_tokens=4000, system=SYSTEM, messages=messages,
                output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
            )
        except Exception as e:  # network, auth, rate limit: the ruling still renders
            result.notice = f"Court arguments unavailable ({type(e).__name__}). " \
                            "The ruling and numbers are unaffected."
            break
        if resp.stop_reason == "refusal":
            result.notice = "Court arguments unavailable (the model declined)."
            break
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raw, errors = {}, ["response was not valid JSON"]
            passed = {}
        else:
            passed, errors = validate(raw, ids)
        if not errors:
            break
        if attempt < MAX_CALLS - 1:
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": "Fix these validation errors and "
                          "return the full JSON again:\n- " + "\n- ".join(errors)}]
        else:
            result.notice = WITHHELD
    for section, args in passed.items():
        result.arguments[section] = [Argument(render(a.text, items), a.evidence_ids)
                                     for a in args]
    return result
