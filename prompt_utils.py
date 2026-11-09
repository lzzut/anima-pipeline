"""JSON parsing and safe output names shared by local generation entries."""

import json
import re


def robust_json_parse(text):
    if not text:
        raise ValueError("AI返回内容为空")
    text = text.strip()
    text = re.sub("^```(?:json)?\\s*", "", text)
    text = re.sub("\\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and (end > start):
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法解析JSON，原始内容前200字符：{text[:200]}")


def _slug(s, n=54):
    s = re.sub("[^a-z0-9]+", "_", str(s).lower()).strip("_")
    return s[:n] or "combo"
