"""Pure visibility projection for Anima prompt content.

This module neither changes character/body facts nor invents visible details.
It only omits explicitly out-of-frame clauses from a rendering copy. Ambiguous
tags, character/work labels, artists, and malformed weighted groups are kept.
"""

import copy
from dataclasses import dataclass
import re

_NORMAL_BUDGETS = {
    "face_priority": 6,
    "eye_colors": 4,
    "expression_priority": 4,
    "core_features": 6,
    "appearance": 8,
    "grounded_appearance": 8,
    "hybrid_features": 12,
    "outfit": 10,
    "body": 6,
    "expression": 4,
    "pose": 4,
    "composition": 3,
    "depth": 2,
    "lighting": 4,
    "scene_foreground": 2,
    "scene_midground": 2,
    "scene_background": 2,
}


def _spec(label, crop, anchor, avoid, overrides=None, scene_budget=2, scene_total_budget=None):
    budgets = dict(_NORMAL_BUDGETS)
    budgets.update(overrides or {})
    return {
        "label": label,
        "framing": label,
        "crop": crop,
        "anchor": anchor,
        "avoid": avoid,
        "field_budgets": budgets,
        "scene_budget": scene_budget,
        "scene_total_budget": scene_total_budget,
    }


_SPECS = {
    "close-up": _spec(
        "close-up",
        "head, neck and shoulders",
        "close-up, head and shoulders, head fully in frame, space above head",
        "full body, cowboy shot, waist-up, head out of frame",
        {
            "face_priority": 8,
            "hybrid_features": 10,
            "outfit": 4,
            "body": 4,
            "pose": 3,
            "scene_foreground": 0,
            "scene_midground": 0,
            "scene_background": 1,
            "depth": 2,
        },
        scene_budget=1,
        scene_total_budget=3,
    ),
    "portrait": _spec(
        "portrait",
        "head to upper chest",
        "portrait, head to upper chest, head fully in frame, space above head",
        "full body, cowboy shot, waist-up, head out of frame",
        {
            "face_priority": 8,
            "hybrid_features": 10,
            "outfit": 5,
            "body": 4,
            "scene_foreground": 0,
            "scene_midground": 1,
            "scene_background": 2,
            "depth": 3,
        },
        scene_total_budget=4,
    ),
    "upper body": _spec(
        "upper body",
        "head to waist",
        "upper body, waist-up, head fully in frame, space above head",
        "face close-up, extreme close-up, full body, head out of frame",
        {"outfit": 8, "pose": 5, "scene_foreground": 1, "scene_midground": 1},
    ),
    "cowboy shot": _spec(
        "cowboy shot",
        "head to mid-thigh",
        "cowboy shot, head to mid-thigh, head fully in frame",
        "face close-up, extreme close-up, full body, head out of frame",
    ),
    "full body": _spec(
        "full body",
        "head to toe",
        "full body, head to toe, feet in frame, head fully in frame",
        "close-up, upper body, cropped feet, head out of frame",
    ),
}
_GROUPS = {
    "portrait/close-up": {
        "base": "portrait",
        "prompt_tag": "portrait",
        "crop": "head and shoulders to chest, above the waist",
        "anchor": "portrait, head fully in frame, space above head",
        "avoid": "full body, cowboy shot, waist-up, head out of frame",
        "allowed_negative_tags": (
            "portrait",
            "close-up",
            "close up",
            "head and shoulders",
            "head to upper chest",
            "head to chest",
            "chest-up",
            "collarbone-up",
            "bust",
            "bust shot",
        ),
    },
    "cowboy/full body": {
        "base": "full body",
        "prompt_tag": "full body",
        "crop": "head to thighs or full length, with no fixed lower crop line",
        "anchor": "full body, head fully in frame, space above head",
        "avoid": "close-up, portrait, upper body, head out of frame",
        "allowed_negative_tags": (
            "cowboy shot",
            "full body",
            "full-length",
            "full length",
            "wide shot",
            "head to mid-thigh",
            "head-to-mid-thigh framing",
            "head to toe",
            "head-to-toe",
            "feet in frame",
            "feet visible",
            "legs visible",
            "standing legs visible",
            "cropped feet",
            "missing feet",
            "cropped legs",
            "no ground shadow",
            "no ground shadows",
            "no cast shadow",
            "no cast shadows",
            "no contact shadow",
            "no contact shadows",
        ),
    },
}
FRAMING_GROUP_NAMES = frozenset(_GROUPS)


def framing_spec(framing):
    """Return an independent spec for one exact framing label, or None.

    Whitespace/case are harmless; only the two named production groups are
    accepted as combined labels. Callers may safely adjust the returned dictionary.
    """
    key = re.sub("\\s+", " ", str(framing or "").strip().lower())
    if key in _GROUPS:
        group = _GROUPS[key]
        spec = copy.deepcopy(_SPECS[group["base"]])
        spec.update({name: value for name, value in group.items() if name != "base"})
        spec.update(group=key, framing=key)
        return spec
    spec = copy.deepcopy(_SPECS.get(key))
    if spec and key in ("close-up", "portrait"):
        from config import ANIMA_COMPLETE_HEAD_PRIORITY

        if ANIMA_COMPLETE_HEAD_PRIORITY:
            spec["complete_head_priority"] = True
            if key == "close-up":
                spec["crop"] = "head to collarbones with a small upper-chest buffer"
                spec["anchor"] = (
                    "head and shoulders, collarbone-up, head fully in frame, space above head"
                )
            else:
                spec["crop"] = "head to chest, above the waist"
                spec["anchor"] = "portrait, chest-up, head fully in frame, space above head"
    return spec


def prompt_framing(framing):
    spec = framing_spec(framing)
    return spec.get("prompt_tag", framing) if spec else framing


def content_directive(framing, channel=None):
    spec = framing_spec(framing)
    if spec is None:
        return ""
    label = spec["label"]
    if spec.get("group") == "portrait/close-up":
        visible = "近景合并接受头肩至胸像，不强制锁骨或上胸的单一裁切线；完整头部和已有头饰优先，画面下缘在腰部以上。只写可见的领口、肩部或胸前衣料，不要求腰饰、裙摆、腿脚或地面入镜，不把画外饰品搬到脸上。以视线、头部和肩向表达动作，不为了手势拉远镜头。"
    elif spec.get("group") == "cowboy/full body":
        visible = "较远景合并接受七分身至全身，展示头部、躯干和大腿；下缘可在大腿附近，也可延伸至脚部，不强制精确大腿中线或脚部必须入镜。以完整动作、躯干、腰部和大腿范围的服装为主；鞋袜、脚部和地面支撑仅在实际入画时描述，不要为了展示它们强制拉远。候选动作共享同一宽范围，不用更换镜头制造变化。"
    elif label == "close-up":
        visible = "只展示完整头部、头发/已有头饰、颈部和肩部；不要要求展示胸腰、裙摆、腰饰、臀腿、脚或鞋。动作通过已有的视线、头部和肩向表现，不要补步伐、重心、提裙摆或画外手部动作。"
    elif label == "portrait":
        visible = "展示完整头部至上胸，允许领口、已有颈饰和上胸可见衣料；不要要求展示腰臀、下装、腿脚或地面。不要把胸针或腰饰搬到脸上，动作以视线、头部、肩向为主；原构思没有画内手势就不要硬加手。"
    elif label == "upper body":
        visible = "展示完整头部至腰部，保留角色自己的可见胸腰轮廓、上衣和简单手势；不写腿脚姿态、鞋袜、低位裙摆动作或地面接触。腰部已有配饰可保留，不要为了展示它改变取景范围。"
    elif label == "cowboy shot":
        visible = "展示完整头部至大腿中部，可保留躯干、手势、腰饰和大腿上部细节；不要要求展示膝盖以下、脚踝、鞋袜或脚与地面的接触。"
    else:
        visible = "展示完整头部至脚部；可描述现有完整动作、鞋袜和真实地面支撑。"
    if spec.get("complete_head_priority"):
        if label == "close-up":
            visible = "优先展示完整发顶、头部与颈肩，下缘以锁骨为目标，允许少量上胸和领口作为缓冲；不要为了把脸放大而裁发顶，不能扩成展示完整胸部、腰腹或腿脚的图。只写已有的视线、头部与肩向动作，不补低位手势或步伐。"
        else:
            visible = "优先展示完整发顶至胸部下缘，形成与锁骨近景明显不同的胸像；允许已有上衣、胸前细节和实际画内手势，画面止于腰部以上，不要求腰线、腰饰、腹部、臀腿、脚或地面入镜，不把腰饰挪到胸口。"
    variant = (
        "稳定版的各候选动作都应在这个可见范围内变化，不新增配饰、身体比例或机位。"
        if channel == "stable"
        else (
            "灵动版保留符合人设的动作瞬间，但不要靠画外肢体动作或拉远镜头制造动态。"
            if channel == "dynamic"
            else "候选动作和构图都使用同一个可见范围。"
        )
    )
    environment = (
        (
            "近景背景使用本主题已有的一至两个局部环境线索和少量衬托，例如肩后或画面边缘可见的环境、材质、色光与适当虚化；不要只写天空或纯色，也不要搬入全身图的完整场景清单。scene_foreground、scene_mi"
            "dground、scene_background共享简短内容，不要求每层填满；不要求完整道路、整间房、完整海岸或地面入画，不新增未选场景的道具。depth按本次近景保留浅景深、局部虚化或清晰环境的实际选择，不与"
            "详细背景模板互相覆盖。"
        )
        if label in ("close-up", "portrait")
        else "背景只需能支持主题的少量可见环境，光源方向和环境反光保留；"
    )
    group_instruction = (
        f"这是合并景别分类，composition只使用主镜头标签 {spec['prompt_tag']}；不要输出带斜杠的分类名，也不要同时堆两个镜头标签，不要求区分类内原有两档。"
        if spec.get("group")
        else ""
    )
    return (
        f"\n【按景别生成实际画面内容】本次景别 {spec.get('group', label)}，可见范围 {spec['crop']}。"
        + group_instruction
        + visible
        + variant
        + (
            "body 仍记录该角色完整的官方体型资料，不要为近景改造身材或统一体型；其他画面字段只写本景别实际可见内容，画外设定不要求入镜。头顶上方保留少量背景余量，头发与已有头饰完整；头饰不存在时不新增。头发、瞳色/瞳形"
            "、神态及已证实存在的头面部/颈部配饰优先；没有的饰品不补齐，不把画外饰品改成脸饰或项链。"
        )
        + environment
        + "近景不写地面投影、脚印或完整三层场景。泳装/海边等涉水主题保留 water droplets on skin, wet hair。\n"
    )


@dataclass
class _Piece:
    text: str = ""
    children: list | None = None
    prefix: str = ""
    opening: str = ""
    closing: str = ""
    weight: str = ""
    protected: bool = False
    keep: bool = True

    def render(self):
        if not self.keep:
            return ""
        if self.children is None:
            return self.text
        inside = ", ".join((value for child in self.children if (value := child.render())))
        return self.prefix + self.opening + inside + self.weight + self.closing if inside else ""


_SPLIT_SPECIAL = re.compile("[\\\\()\\[\\]{},]")
_SPLIT_PAIRS = {")": "(", "]": "[", "}": "{"}


def _split_top(value):
    """Split commas only outside balanced, unescaped weighting brackets."""
    stack, start, parts = ([], 0, [])
    match = _SPLIT_SPECIAL.search(value)
    while match is not None:
        index = match.start()
        char = value[index]
        if char == "\\":
            match = _SPLIT_SPECIAL.search(value, index + 2)
            continue
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if not stack or stack.pop() != _SPLIT_PAIRS[char]:
                return ([value.strip()], False)
        elif not stack:
            if value[start:index].strip():
                parts.append(value[start:index].strip())
            start = index + 1
        match = _SPLIT_SPECIAL.search(value, index + 1)
    if stack:
        return ([value.strip()], False)
    if value[start:].strip():
        parts.append(value[start:].strip())
    return (parts, True)


def content_enabled(workflow, framing):
    """Keep the feature scoped to known crops in the two Anima workflows."""
    from config import ANIMA_FRAMING_CONTENT

    return bool(
        ANIMA_FRAMING_CONTENT
        and workflow in ("api", "anima_flow")
        and (framing_spec(framing) is not None)
    )


def split_prompt_tags(value):
    """Return complete top-level clauses; malformed groups stay opaque."""
    return _split_top(str(value or ""))[0]


_WEIGHT_END = re.compile("(:\\s*[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+))\\s*$")


def _parse_piece(text):
    if "@" in text:
        return _Piece(text=text, protected=True)
    wrapper = re.match("(?is)^(wearing\\s+)?([\\(\\[])(.*)([\\)\\]])$", text)
    if wrapper and (wrapper[2], wrapper[4]) in (("(", ")"), ("[", "]")):
        inner, weight = (wrapper[3], "")
        match = _WEIGHT_END.search(inner)
        if match:
            candidate = inner[: match.start()]
            _, balanced = _split_top(candidate)
            if balanced:
                inner, weight = (candidate, match[1])
        children, balanced = _split_top(inner)
        if balanced:
            return _Piece(
                children=[_parse_piece(child) for child in children],
                prefix=wrapper[1] or "",
                opening=wrapper[2],
                closing=wrapper[4],
                weight=weight,
            )
    protected = bool(re.search("[()\\[\\]{}]", text) or ":" in text)
    return _Piece(text=text, protected=protected)


def _leaves(pieces):
    for piece in pieces:
        if piece.children is None:
            yield piece
        else:
            yield from _leaves(piece.children)


def _canonical(text):
    return re.sub("\\s+", " ", str(text).replace("_", " ").strip().lower())


def _rx(pattern):
    return re.compile("(?i)\\b(?:" + pattern + ")\\b")


_WET = {"water droplets on skin", "wet hair"}
_HEAD_DETAIL = _rx(
    (
        "headband|headwear|headdress|hair(?:band|clip|pin| ornament| ribbon| bow)|hair ornament|hair ribbon|hair "
        "bow|hair flower|hat|crown|tiara|beret|earrings?|ear "
        "cuffs?|eyepatch|glasses|sunglasses|headphones?|headset|choker|necklace|neck "
        "ribbon|collar|horns?|halo|mask"
    )
)
_UPPER_BOUNDARY = re.compile(
    (
        "(?i)(?:(?:visible|bare|exposed) )?(?:navel|midriff|upper "
        "abdomen|waistline|waistband)|(?:shirt|blouse|sweater|jacket|top) hem(?: at (?:the )?waist)?"
    )
)
_HEIGHT = re.compile(
    "(?i)\\b(?:(?:around|about|approximately|roughly)\\s+)?\\d{2,3}(?:\\.\\d+)?\\s*(?:cm|centimeters?|centimetres?)(?:\\s+tall)?\\b"
)
_FEET = _rx(
    (
        "(?:bare|both|left|right|her|his|their) feet|(?:bare|left|right) foot|feet (?:visible|in "
        "frame|resting|on|touching|planted|apart|together)|foot (?:visible|in "
        "frame|resting|on|touching|planted)|(?:crossed|bare) ankles|ankles? (?:crossed|visible)|ankle "
        "(?:strap|straps|bracelet)|shoes?|boots?|sandals?|sneakers?|loafers?|high "
        "heels?|socks?|stockings?|thighhighs|thigh highs|pantyhose|tights|calves|shins|lower "
        "legs?|knees?|kneecaps?|knee[- ]highs?"
    )
)
_LEGS = _rx(
    (
        "long (?:slender |slim )?legs|long[- ]legged|legs "
        "visible|(?:left|right|both|crossed|bare|spread|slender|slim|muscular|shapely) legs?|legs? "
        "(?:crossed|apart|raised|extended|bent|straight|spread|visible)|thighs?|thigh "
        "(?:strap|straps|holster|band)|garters?|leg (?:strap|holster)"
    )
)
_LOWER_CLOTHES = _rx(
    "skirts?|sarongs?|pareos?|trousers?|pants|shorts|bikini bottoms?|swimsuit bottoms?|swim bottoms?|underpants|panties|hakama|loincloth"
)
_WAIST_HIPS = _rx(
    (
        "waist|waistline|waistband|hips?|hipbone|pelvis|pelvic|buttocks?|midriff|navel|belly|abdomen|abdominal|obi"
        "|belts?|hourglass(?: figure| curves)?|full[- ]body proportions"
    )
)
_HIPS_ONLY = _rx("hips?|hipbone|pelvis|pelvic|buttocks?")
_CHEST = _rx(
    "(?:full|large|small|medium|flat) (?:bust|chest)|breasts?|cleavage|bare chest|chest tattoo|chest ornament|bikini top|bra top"
)
_GROUND = _rx(
    (
        "(?:grounded|grounding|ground contact|ground[- ]contact) (?:contact )?shadows?|(?:cast|contact) shadows? "
        "(?:on|across|under|beneath) (?:the )?(?:floor|sand|ground|path)|cast shadow on the floor|character "
        "grounded|grounding the character|feet? (?:on|touching|resting on|planted on) (?:the "
        ")?(?:ground|floor|sand)|(?:sand|ground|path|shoreline) with (?:faint )?footprints|footprints|shallow "
        "water (?:around|at) (?:her |his |their )?(?:feet|ankles)"
    )
)
_WHOLE_MOTION = _rx(
    (
        "walking|running|mid[- ]step|mid[- ]stride|striding|footsteps?|contrapposto|weight shift|weight "
        "shifted|shifting weight|weight (?:on|onto)|hips? (?:set|cocked)|dancing|jumping"
    )
)
_UPPER_GAIT_TAGS = {
    "walking",
    "running",
    "striding",
    "mid-step",
    "mid step",
    "mid-stride",
    "mid stride",
    "footstep",
    "footsteps",
}
_HEM_ACTION = _rx(
    (
        "(?:holding|lifting|pulling|gripping|adjusting|raising|tugging)(?: the| her| his| their)?(?: edge of(?: "
        "her| his| their| the)?)? (?:sarong|skirt|dress hem|hem|waistband)|hands? (?:on|by|near|resting on) (?:her"
        " |his |their |the )?(?:lap|thigh|hip)|hands? resting low|sarong (?:hem|knot)|skirt hem"
    )
)
_HAND_TEMPLATE = {
    "detailed hands",
    "five fingers",
    "realistic arm structure",
    "perfect hands",
    "detailed fingers",
    "anatomically correct hands",
}
_LOW_HAND = _rx(
    (
        "arms? relaxed at (?:her |his |their )?sides?|hands? (?:relaxed|loose) (?:at|by) (?:her |his |their "
        ")?sides?|hands? (?:on|at) (?:her |his |their )?waist|hand on hip|arms? crossed (?:over|across) (?:her "
        "|his |their )?chest"
    )
)
_GROUND_NEGATIVE = {
    "no cast shadow",
    "no cast shadows",
    "no contact shadow",
    "no contact shadows",
    "no ground shadow",
    "no ground shadows",
    "cropped feet",
    "missing feet",
    "bad feet",
}


def _drop_reason(value, label, negative=False, complete_head=False):
    low = _canonical(value)
    if low in _WET:
        return None
    if negative:
        return "off-frame ground/feet obligation" if low in _GROUND_NEGATIVE else None
    if _GROUND.search(low):
        return "off-frame ground contact"
    if _FEET.search(low):
        return "below the crop: knees, lower legs or feet"
    if label == "cowboy shot":
        return None
    if _LEGS.search(low) or _LOWER_CLOTHES.search(low):
        return "below the crop: legs or lower clothing"
    if _HEM_ACTION.search(low):
        return "action targets clothing/body below the crop"
    if label == "upper body":
        if low in _UPPER_GAIT_TAGS:
            return "off-frame gait tag in waist-up crop"
        return "below the waist-up crop: hip detail" if _HIPS_ONLY.search(low) else None
    if _WAIST_HIPS.search(low):
        return "below the crop: waist, hips or whole-body shape"
    if _WHOLE_MOTION.search(low):
        return "whole-body locomotion or weight instruction"
    if low in _HAND_TEMPLATE:
        return "generic hand-detail template outside the close crop"
    if _LOW_HAND.search(low):
        visible_chest_arms = (
            complete_head
            and label == "portrait"
            and re.search("\\barms? crossed (?:over|across) (?:her |his |their )?chest\\b", low)
        )
        if not visible_chest_arms:
            return "hands below the close crop"
    if low in {"detailed background", "cinematic composition", "atmospheric perspective"}:
        return "generic scene-expansion template outside the close crop"
    if label == "close-up" and _CHEST.search(low):
        local_clothing = complete_head and bool(
            re.search("\\b(?:bikini top|bra top|upper chest (?:tattoo|ornament))\\b", low)
        )
        full_chest_obligation = bool(
            re.search(
                "\\b(?:(?:full|large|small|medium|flat) (?:bust|chest)|breasts?|cleavage|bare chest)\\b",
                low,
            )
        )
        if not local_clothing or full_chest_obligation:
            return "chest detail outside the head/neck/shoulder crop"
    return None


def _project_text(
    value,
    spec,
    audit,
    field_name,
    *,
    budget=None,
    negative=False,
    protected_labels=(),
    priority_boundary=None,
):
    original = str(value or "")
    fragments, balanced = _split_top(original)
    if not balanced:
        audit.append(
            {"field": field_name, "action": "keep", "reason": "unbalanced input kept opaque"}
        )
        return original
    pieces = [_parse_piece(fragment) for fragment in fragments]
    protected_keys = {_canonical(item) for item in protected_labels if item}
    for leaf in _leaves(pieces):
        key = _canonical(leaf.text)
        if leaf.protected or key in protected_keys or key in _WET:
            continue
        reason = _drop_reason(
            leaf.text,
            spec["label"],
            negative,
            complete_head=spec.get("complete_head_priority", False),
        )
        if reason:
            leaf.keep = False
            audit.append(
                {"field": field_name, "action": "drop", "tag": leaf.text, "reason": reason}
            )
            continue
        if not negative:
            trimmed = _HEIGHT.sub("", leaf.text).strip(" ,;-")
            trimmed = re.sub("\\s{2,}", " ", trimmed)
            if trimmed != leaf.text:
                audit.append(
                    {
                        "field": field_name,
                        "action": "trim",
                        "tag": leaf.text,
                        "rendered": trimmed,
                        "reason": "height measurement outside close crop",
                    }
                )
                leaf.text, leaf.keep = (trimmed, bool(trimmed))
    leaves = [leaf for leaf in _leaves(pieces) if leaf.keep and leaf.text]
    if budget is not None and len(leaves) > budget:
        mandatory = [
            leaf
            for leaf in leaves
            if leaf.protected or _canonical(leaf.text) in protected_keys | _WET
        ]
        mandatory_ids = {id(leaf) for leaf in mandatory}
        remaining = [leaf for leaf in leaves if id(leaf) not in mandatory_ids]
        boundary = next(
            (
                leaf
                for leaf in remaining
                if priority_boundary is not None and _canonical(leaf.text) == priority_boundary
            ),
            None,
        )
        priority = [boundary] if boundary is not None else []
        priority += [
            leaf
            for leaf in remaining
            if leaf is not boundary and _HEAD_DETAIL.search(_canonical(leaf.text))
        ]
        priority_ids = {id(leaf) for leaf in priority}
        priority += [leaf for leaf in remaining if id(leaf) not in priority_ids]
        keep_ids = mandatory_ids | {
            id(leaf) for leaf in priority[: max(0, budget - len(mandatory))]
        }
        for leaf in leaves:
            if id(leaf) not in keep_ids:
                leaf.keep = False
                audit.append(
                    {
                        "field": field_name,
                        "action": "drop",
                        "tag": leaf.text,
                        "reason": (
                            "visible-field budget; existing waist-up landmark prioritized"
                            if boundary is not None
                            else "visible-field budget; existing head/neck accessories prioritized"
                        ),
                    }
                )
    return ", ".join((text for piece in pieces if (text := piece.render())))


def omit_framing_tags(value, removed):
    fragments, balanced = _split_top(str(value or ""))
    if not balanced:
        return value
    pieces = [_parse_piece(fragment) for fragment in fragments]
    for leaf in _leaves(pieces):
        if not leaf.protected and _canonical(leaf.text) in removed:
            leaf.keep = False
    return ", ".join((text for piece in pieces if (text := piece.render())))


def _empty_audit(spec):
    return {
        "framing": spec.get("group", spec["label"]) if spec else None,
        "active": bool(spec and spec["label"] != "full body"),
        "changes": [],
        "source_body_preserved": True,
        "invented_details": 0,
    }


_SCENE_FIELDS = ("scene_foreground", "scene_midground", "scene_background")
_SCENE_PERSON = _rx(
    (
        "(?:her|his|their|the subject's) (?:hair|eyes|face|chest|shoulders?|hands?|legs?|body)|eyes?|eyelashes|eye"
        "brows|necklaces?|earrings?|sunglasses|bikini|breasts?|cleavage|(?:small|large|full|medium) "
        "(?:bust|chest)|hand holding|palm of (?:her|his|the) hand"
    )
)
_SCENE_REFERENCE = re.compile(
    "(?i)(?P<environment>.+?)\\s+(?:behind|beside|next to)\\s+(?:her|his|their|the subject's)\\s+(?:head|shoulders?)"
)
_ENVIRONMENT_ENTITY = re.compile(
    (
        "(?i)\\b(?:sea|ocean|water|waves?|horizon|beach|shore|sand|sky|clouds?|umbrellas?|trees?|leaves|foliage|bra"
        "nches|flowers?|forest|mountains?|snow|windows?|walls?|curtains?|bookshelves|bookshelf|shelves|lamps?|buil"
        "dings?|street|garden)\\b$"
    )
)
_SCENE_PERSON_REMAINDER = _rx(
    (
        "hair|skin|face|eyes?|eyelashes|eyebrows|chest|shoulders?|hands?|legs?|body|necklaces?|earrings?|sunglasse"
        "s|bikini|breasts?|cleavage|bust|wearing|holding|standing|sitting|leaning|girls?|boys?|women|woman|men|man"
        "|people|persons?|characters?|subjects?|figures?|silhouettes?|swimmers?|shirts?|tops?|blouses?|dresses|dre"
        "ss|coats?|jackets?|garments?|clothing|fabric|sleeves?|patterns?|patterned"
    )
)
_SCENE_COMPLEX_PREFIX = _rx("by|with|in|on|at|of|and|or")
_GENERAL_SCENE = re.compile(
    (
        "(?i)^(?:(?:sky|clouds?|sunlight|sunshine|ambient|light|color|gradient|clear|blue|white|soft|thin|few|brig"
        "ht|pale|warm|cool|golden|natural|summer|night|starry|overcast|cloudy|a|the|and|with|in|above|overhead)\\b["
        "\\s-]*)+$"
    )
)
_DEPTH_CONTEXT = _rx("depth of field|blurred|bokeh|background|behind")


def _scene_person_detail(value):
    """A complete environment relation may use a person as a location only."""
    low = _canonical(value)
    relation = _SCENE_REFERENCE.fullmatch(low)
    if relation:
        environment = relation["environment"]
        if (
            _ENVIRONMENT_ENTITY.search(environment)
            and (not _SCENE_PERSON_REMAINDER.search(environment))
            and (not _LOWER_CLOTHES.search(environment))
            and (not _SCENE_COMPLEX_PREFIX.search(environment))
            and (not _SCENE_PERSON.search(environment))
        ):
            return False
    return bool(_SCENE_PERSON.search(low))


def _project_near_environment(view, spec, audit, protected):
    """Select existing environment clauses across fields; never invent a scene.

    Groups remain atomic. Opaque identity/artist/malformed input is retained as
    an audited exception instead of being truncated to force a hard quota.
    """
    candidates, preserved = ([], {})
    seen = set()
    protected_keys = {_canonical(item) for item in protected if item}
    for field in _SCENE_FIELDS:
        if not isinstance(view.get(field), str):
            continue
        value = view[field]
        fragments, balanced = _split_top(value)
        if not balanced:
            preserved[field] = value
            audit.append(
                {"field": field, "action": "keep", "reason": "opaque scene budget exception"}
            )
            continue
        for index, text in enumerate(fragments):
            key = _canonical(text)
            piece = _parse_piece(text)
            if (
                "@" in text
                or key in protected_keys
                or (piece.protected and re.search("[()\\[\\]{}]", text))
            ):
                candidates.append((field, index, text, None))
                audit.append(
                    {
                        "field": field,
                        "action": "keep",
                        "tag": text,
                        "reason": "opaque identity/artist scene budget exception",
                    }
                )
                continue
            leaves = list(_leaves([piece]))
            reasons = [
                _drop_reason(
                    leaf.text,
                    spec["label"],
                    complete_head=spec.get("complete_head_priority", False),
                )
                for leaf in leaves
            ]
            if any(reasons):
                audit.append(
                    {
                        "field": field,
                        "action": "drop",
                        "tag": text,
                        "reason": "scene clause/group outside crop: "
                        + next((r for r in reasons if r)),
                    }
                )
                continue
            if any((_scene_person_detail(leaf.text) for leaf in leaves)):
                audit.append(
                    {
                        "field": field,
                        "action": "drop",
                        "tag": text,
                        "reason": "person detail is not an independent environment cue",
                    }
                )
                continue
            if key in _WET or all((_canonical(leaf.text) in _WET for leaf in leaves)):
                candidates.append((field, index, text, None))
                continue
            if key in seen:
                audit.append(
                    {
                        "field": field,
                        "action": "drop",
                        "tag": text,
                        "reason": "duplicate environment clause across scene fields",
                    }
                )
                continue
            seen.add(key)
            generic = all((_GENERAL_SCENE.search(_canonical(leaf.text)) for leaf in leaves))
            candidates.append((field, index, text, 1 if generic else 0))
    ranked = sorted((item for item in candidates if item[3] is not None), key=lambda item: item[3])
    selected = {(field, index) for field, index, _, _ in ranked[: spec["scene_total_budget"]]}
    for field in _SCENE_FIELDS:
        if not isinstance(view.get(field), str):
            continue
        if field in preserved:
            view[field] = preserved[field]
            continue
        kept = []
        for origin, index, text, rank in candidates:
            if origin != field:
                continue
            if rank is None or (origin, index) in selected:
                kept.append(text)
            else:
                audit.append(
                    {
                        "field": field,
                        "action": "drop",
                        "tag": text,
                        "reason": "shared near-scene budget; concrete environment before generic sky",
                    }
                )
        view[field] = ", ".join(kept)


def _project_near_depth(value, spec, audit, protected):
    clean = _project_text(value, spec, audit, "depth", protected_labels=protected)
    fragments, balanced = _split_top(clean)
    if not balanced:
        return clean
    ranked = sorted(enumerate(fragments), key=lambda item: not _DEPTH_CONTEXT.search(item[1]))
    chosen = {i for i, _ in ranked[: spec["field_budgets"]["depth"]]}
    for index, text in enumerate(fragments):
        if index not in chosen:
            audit.append(
                {
                    "field": "depth",
                    "action": "drop",
                    "tag": text,
                    "reason": "near depth budget; depth and environment relation before face focus",
                }
            )
    return ", ".join((text for index, text in enumerate(fragments) if index in chosen))


_FEATURE_SOURCE_FIELDS = ("face_priority", "core_features", "appearance", "hybrid_features")
_FEATURE_GENERIC = {
    "delicately rendered facial features",
    "detailed eyes",
    "detailed face",
    "soft skin shading",
    "distinct hair strands with subtle highlights",
    "beautiful detailed eyes",
    "intricate hair details",
    "detailed hair",
}
_FEATURE_HAIR_STRUCTURE = re.compile(
    (
        "(?i)(?:(?:long|short|messy|loose|high|low|side|single|double|braided) )*(?:ponytail|twintails|twin "
        "tails|braids?|buns?|bob cut|pixie cut|wavy hair|curly hair|straight hair|afro)(?: with (?:long )?(?:loose"
        " )?strands? over (?:her |his |their )?shoulder)?"
    )
)
_FEATURE_FIXED_MARK = re.compile(
    (
        "(?i)(?:(?:small|single|faint|prominent|facial) )?(?:mole|scar|birthmark|freckles|facial tattoo)(?: "
        "(?:under|below|above|on|across) (?:the |her |his |their )?(?:left |right "
        ")?(?:eye|cheek|lip|face|nose|forehead))?"
    )
)
_FEATURE_FACE_STRUCTURE = _rx(
    (
        "almond eyes|narrow eyes|slanted eyes|slanting eyes|round eyes|arched eyebrows|thin eyebrows|thick "
        "eyebrows|straight eyebrows|eyelashes|eyes without highlights"
    )
)
_FEATURE_HAIR_MODIFIERS = {
    "long",
    "short",
    "medium",
    "messy",
    "loose",
    "high",
    "low",
    "side",
    "single",
    "double",
    "twin",
    "braided",
    "wavy",
    "curly",
    "straight",
    "black",
    "white",
    "silver",
    "gray",
    "grey",
    "red",
    "blue",
    "green",
    "purple",
    "violet",
    "magenta",
    "pink",
    "blonde",
    "blond",
    "brown",
    "aqua",
    "teal",
    "orange",
    "wine-red",
    "wine",
    "dark",
    "light",
}
_FEATURE_ACCESSORY_MODIFIERS = {
    "black",
    "white",
    "red",
    "blue",
    "green",
    "purple",
    "pink",
    "brown",
    "dark",
    "light",
    "gold",
    "golden",
    "silver",
    "pearl",
    "round",
    "oval",
    "square",
    "pince-nez",
    "single",
    "small",
    "large",
}


def _feature_simple(piece):
    """Describe only one plain leaf or one simple, intact weighted leaf."""
    if piece.children is None:
        return None if piece.protected else (piece.text, "")
    if (
        piece.prefix
        or len(piece.children) != 1
        or piece.children[0].children is not None
        or piece.children[0].protected
    ):
        return None
    return (piece.children[0].text, piece.opening + piece.weight + piece.closing)


def _feature_semantic(text):
    """Small equivalence grammar; unrecognised prose has no semantic key."""
    low = _canonical(text)
    hair = re.fullmatch(
        "(?:(.*?) )?(ponytail|twintails|twin tails|braid|braids|bun|buns|hair)", low
    )
    if hair:
        modifiers = frozenset((hair[1] or "").split())
        if modifiers <= _FEATURE_HAIR_MODIFIERS:
            return ("hair", hair[2], "", modifiers)
    accessory = re.fullmatch(
        (
            "(?:(.*?) )?(sunglasses|glasses|eyewear|earring|earrings) (?:(?:resting )?on (?:top of "
            ")?(?:(?:her|his|their) )?head|on (?:the )?(left|right) ear)"
        ),
        low,
    )
    if accessory:
        modifiers = frozenset((accessory[1] or "").split())
        if modifiers <= _FEATURE_ACCESSORY_MODIFIERS:
            return ("accessory", accessory[2], accessory[3] or "head", modifiers)
    return None


def _feature_rank(text):
    low = _canonical(text)
    if low in _FEATURE_GENERIC:
        return 4
    if _FEATURE_HAIR_STRUCTURE.fullmatch(low) or _FEATURE_FIXED_MARK.fullmatch(low):
        return 0
    if _HEAD_DETAIL.search(low) or re.search(
        "\\b(?:bangs|sidelocks|ahoge|eye shape|almond eyes|eyebrows)\\b", low
    ):
        return 1
    if re.search("\\b(?:hair|eyes|eyeshadow|eyeliner|lipstick|lips)\\b", low):
        return 2
    return 3


def retain_character_features(structured, spec, protected_labels=(), consumed_face=None):
    """Select existing visible features from the untruncated source pool.

    Only simple, compatible descriptions are deduplicated. Unknown groups,
    identity/artist labels and malformed fields remain opaque. No fact or
    replacement wording is constructed, and the selected clauses keep order.
    """
    audit, pool, seen = ([], [], set())
    protected = {_canonical(item) for item in protected_labels if item}
    face_keys = {_canonical(item) for item in _split_top(str(consumed_face or ""))[0]}
    for field in _FEATURE_SOURCE_FIELDS:
        value = structured.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        clean = _project_text(
            value, spec, audit, field + "(feature-source)", protected_labels=protected_labels
        )
        fragments, balanced = _split_top(clean)
        for fragment in fragments:
            key = _canonical(fragment)
            if key in seen:
                audit.append(
                    {
                        "field": field,
                        "action": "drop",
                        "tag": fragment,
                        "reason": "duplicate complete feature clause",
                    }
                )
                continue
            piece = _parse_piece(fragment)
            simple = _feature_simple(piece)
            leaves = list(_leaves([piece]))
            opaque = (
                not balanced
                or any((leaf.protected for leaf in leaves))
                or any((_canonical(leaf.text) in protected for leaf in leaves))
            )
            rank = min((_feature_rank(leaf.text) for leaf in leaves), default=3)
            if field == "face_priority":
                if key in face_keys or not (
                    opaque
                    or rank == 0
                    or _HEAD_DETAIL.search(key)
                    or _FEATURE_FACE_STRUCTURE.search(key)
                ):
                    continue
            seen.add(key)
            pool.append(
                {
                    "text": fragment,
                    "piece": piece,
                    "simple": simple,
                    "semantic": _feature_semantic(simple[0]) if simple else None,
                    "mandatory": opaque or any((_canonical(leaf.text) in _WET for leaf in leaves)),
                    "cost": max(1, len(leaves)),
                    "rank": rank,
                    "keep": True,
                }
            )
    for index, item in enumerate(pool):
        if not item["keep"] or item["semantic"] is None or item["mandatory"]:
            continue
        for other in pool[index + 1 :]:
            if not other["keep"] or other["semantic"] is None or other["mandatory"]:
                continue
            a, b = (item["semantic"], other["semantic"])
            if a[:3] != b[:3]:
                continue
            aw, bw = (item["simple"][1], other["simple"][1])
            if aw != bw and (not (a == b and (not aw or not bw))):
                continue
            if not (a[3] <= b[3] or b[3] <= a[3]):
                continue
            loser, winner = (
                (item, other) if a[3] < b[3] or (a == b and bw and (not aw)) else (other, item)
            )
            loser["keep"] = False
            audit.append(
                {
                    "field": "hybrid_features",
                    "action": "drop",
                    "tag": loser["text"],
                    "reason": "compatible feature already expressed by existing clause",
                    "kept": winner["text"],
                }
            )
            if loser is item:
                break
    active = [item for item in pool if item["keep"]]
    budget = spec["field_budgets"]["hybrid_features"]
    chosen = {id(item) for item in active if item["mandatory"]}
    cost = sum((item["cost"] for item in active if item["mandatory"]))
    for item in sorted(
        (item for item in active if not item["mandatory"]), key=lambda item: item["rank"]
    ):
        if cost + item["cost"] <= budget:
            chosen.add(id(item))
            cost += item["cost"]
        else:
            audit.append(
                {
                    "field": "hybrid_features",
                    "action": "drop",
                    "tag": item["text"],
                    "reason": "original visible-feature budget; specific features before generic quality",
                }
            )
    if cost > budget:
        audit.append(
            {
                "field": "hybrid_features",
                "action": "keep",
                "reason": "existing opaque/required feature budget exception",
                "cost": cost,
                "budget": budget,
            }
        )
    return (", ".join((item["text"] for item in pool if id(item) in chosen)), audit)


def project_structured(structured, framing):
    """Return a rendering copy and audit; the source dictionary is untouched.

    Full body/unknown crops are exact deep-copy passthroughs. The rendering copy
    may omit body clauses but is never written back into the complete source.
    """
    view = copy.deepcopy(structured)
    spec = framing_spec(framing)
    audit = _empty_audit(spec)
    if not isinstance(view, dict) or not audit["active"]:
        return (view, audit)
    source_body = copy.deepcopy(structured.get("body"))
    protected = [
        view.get(key, "") for key in ("name_en", "series_en", "name", "series", "character_tag")
    ]
    budgets = spec["field_budgets"]
    feature_source = None
    if view.get("_character_consistency"):
        feature_source = copy.deepcopy(
            view.get("_feature_retention_source")
            or {name: view.get(name) for name in _FEATURE_SOURCE_FIELDS}
        )
        view["_feature_retention_source"] = copy.deepcopy(feature_source)
    boundary_field, boundary_tag = (None, None)
    if spec["label"] == "upper body":
        for name in ("outfit", "body"):
            fragments, balanced = _split_top(str(view.get(name) or ""))
            if not balanced:
                continue
            leaves = _leaves([_parse_piece(fragment) for fragment in fragments])
            boundary_tag = next(
                (
                    _canonical(leaf.text)
                    for leaf in leaves
                    if _UPPER_BOUNDARY.fullmatch(_canonical(leaf.text))
                    and (not _drop_reason(leaf.text, spec["label"]))
                ),
                None,
            )
            if boundary_tag is not None:
                boundary_field = name
                break
    for name, budget in budgets.items():
        if spec["scene_total_budget"] is not None and name in (*_SCENE_FIELDS, "depth"):
            continue
        if isinstance(view.get(name), str):
            view[name] = _project_text(
                view[name],
                spec,
                audit["changes"],
                name,
                budget=budget,
                protected_labels=protected,
                priority_boundary=boundary_tag if name == boundary_field else None,
            )
    if spec["scene_total_budget"] is not None:
        _project_near_environment(view, spec, audit["changes"], protected)
        if isinstance(view.get("depth"), str):
            view["depth"] = _project_near_depth(view["depth"], spec, audit["changes"], protected)
    if feature_source is not None:
        view["hybrid_features"], feature_audit = retain_character_features(
            feature_source, spec, protected, consumed_face=view.get("face_priority")
        )
        audit["feature_retention"] = feature_audit
    else:
        merged, seen = ([], set())
        for name in ("face_priority", "core_features", "appearance", "hybrid_features"):
            fragments, balanced = _split_top(str(view.get(name) or ""))
            if not balanced:
                continue
            for fragment in fragments:
                if name == "face_priority" and (not _HEAD_DETAIL.search(_canonical(fragment))):
                    continue
                key = _canonical(fragment)
                if key and key not in seen:
                    seen.add(key)
                    merged.append(fragment)
        if merged:
            view["hybrid_features"] = _project_text(
                ", ".join(merged),
                spec,
                audit["changes"],
                "hybrid_features(merge)",
                budget=budgets["hybrid_features"],
                protected_labels=protected,
            )
    for name in ("negative", "negatives"):
        if isinstance(view.get(name), str):
            view[name] = _project_text(
                view[name], spec, audit["changes"], name, negative=True, protected_labels=protected
            )
    if isinstance(view.get("pose_variants"), list):
        view["pose_variants"] = [
            (
                _project_text(
                    value,
                    spec,
                    audit["changes"],
                    f"pose_variants[{index}]",
                    budget=budgets["pose"],
                    protected_labels=protected,
                )
                if isinstance(value, str)
                else value
            )
            for index, value in enumerate(view["pose_variants"])
        ]
    audit["source_body_preserved"] = structured.get("body") == source_body
    audit["render_body"] = view.get("body")
    audit["head_accessories_selected"] = [
        fragment
        for fragment in _split_top(str(view.get("hybrid_features") or ""))[0]
        if _HEAD_DETAIL.search(_canonical(fragment))
    ]
    return (view, audit)


def project_prompt(positive, negative, framing):
    """Final visibility safeguard after template rewrites, before artist injection.

    This is omission only: no replacement pose, identity fact, or accessory is
    introduced. Any segment containing an artist marker is left wholly opaque.
    """
    spec = framing_spec(framing)
    audit = _empty_audit(spec)
    if not audit["active"]:
        return (positive, negative, audit)
    result_positive = _project_text(positive, spec, audit["changes"], "positive")
    result_negative = _project_text(negative, spec, audit["changes"], "negative", negative=True)
    return (result_positive, result_negative, audit)
