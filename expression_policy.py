"""Preserve the supplied main expression without prescribing a character mood.

This is text consistency, not personality verification. Unknown expressions and
opaque groups remain untouched. No mood, negative tag, or retry is invented.
"""

import copy
import re
from framing_content import _split_top, _parse_piece, _canonical


def character_directive():
    return (
        "\n【人物事实与主表情 · 来源优先】\n- "
        "官方角色介绍、原作台词或官方设定的已读取正文优先；社区百科正文次之。搜索摘要仅作线索，二创频率仅作参考，不等同官方事实。无法读正文时注明未核实，不把搜索摘要写成已读正文，不补造痣、眉形、饰品或左右眼。\n- "
        "eye_colors 是本稿唯一瞳色字段；其他字段只补眼型、眉形、妆容，不重复填颜色。异色瞳只在有依据时写清左右；来源冲突不以图库首个颜色裁决。\n- expression_priority "
        "只写一套符合本次情境与人物依据的主表情；expression "
        "仅写相容的嘴部/眼睑细节。活泼人物可自然笑，克制人物可保留轻微情绪；不要统一冷脸、微笑、腮红或威严。没有性格正文依据时不要声称已验证人设。允许普通自然动作，不为人设把动作压成同一姿势。\n- 额外返回 "
        "character_evidence_note，区分本次实际读取的URL/事实、仅摘要线索、来源冲突及未核实项；该说明只是待核的来源声明，不能替代工具调用记录。\n"
    )


_AMBIGUOUS_AFFECT = re.compile("(?i)\\b(?:not|no|without|never|unlike|rather|than)\\b")


def _signals(value):
    """Small set of explicit competing affects; calm is compatible with smiles."""
    low = _canonical(value)
    if _AMBIGUOUS_AFFECT.search(low):
        return set()
    return {
        name
        for name, pattern in (
            ("smile", "\\b(?:smil\\w*|smirk\\w*|grin\\w*|laugh\\w*|cheerful|happy|joyful)\\b"),
            ("sad", "\\b(?:sad|sorrowful|crying|weeping|tearful)\\b"),
            ("angry", "\\b(?:angry|furious|scowling|rage)\\b"),
            ("fear", "\\b(?:scared|afraid|frightened|fearful|terrified)\\b"),
            ("serious", "\\b(?:serious|stern|expressionless|stoic)\\b"),
        )
        if re.search(pattern, low)
    }


def _conflicts(main, other):
    if len(main) != 1 or not other or (not main.isdisjoint(other)):
        return False
    opposed = {"sad", "angry", "fear", "serious"}
    return bool(
        "smile" in main
        and other.intersection(opposed)
        or ("smile" in other and main.intersection(opposed))
    )


def prepare_expression(structured):
    """Return a rendering copy and an audit; preserve all supplied main tags."""
    view = copy.deepcopy(structured)
    audit = {
        "scope": "supplied main expression, not verified personality",
        "changes": [],
        "unresolved": [],
    }
    main = str(view.get("expression_priority") or "")
    fragments, balanced = _split_top(main)
    if not balanced or any(
        (_parse_piece(part).protected or _parse_piece(part).children for part in fragments)
    ):
        audit["unresolved"].append("opaque main expression")
        view["_expression_policy"] = True
        return (view, audit)
    if _AMBIGUOUS_AFFECT.search(main):
        audit["unresolved"].append("negated or comparative main affect preserved")
    signals = _signals(main)
    auxiliary = str(view.get("expression") or "")
    clauses, balanced = _split_top(auxiliary)
    if balanced and signals:
        keep = []
        for clause in clauses:
            piece = _parse_piece(clause)
            if _AMBIGUOUS_AFFECT.search(clause):
                audit["unresolved"].append("negated or comparative auxiliary affect preserved")
            if (
                not piece.protected
                and piece.children is None
                and _conflicts(signals, _signals(clause))
            ):
                audit["changes"].append(
                    {
                        "field": "expression",
                        "removed": clause,
                        "reason": "competes with supplied main affect",
                    }
                )
            else:
                keep.append(clause)
        view["expression"] = ", ".join(keep)
    elif not balanced:
        audit["unresolved"].append("opaque auxiliary expression")
    view["_expression_policy"] = True
    audit["main_present"] = bool(main.strip())
    return (view, audit)
