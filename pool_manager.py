# pool_manager.py
import json, os, re
from openai import OpenAI
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

# 允许未设置环境变量时也能导入模块；实际调用会明确返回鉴权错误。
client = OpenAI(api_key=DEEPSEEK_API_KEY or "missing", base_url=DEEPSEEK_BASE_URL)

POOL_FILE = "character_pool.json"
POOL_SIZE = 35
MALE_BLACKLIST_FILE = "male_blacklist.json"
UNKNOWN_COUNTER_FILE = "unknown_counter.json"


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def robust_json_parse(text):
    if not text:
        raise ValueError("AI返回内容为空")
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"无法解析JSON，原始内容前200字符：{text[:200]}")


def ai_generate(system, user, max_tokens=6000, retry=3):
    last_error = None
    for attempt in range(retry):
        try:
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                response_format={"type": "json_object"},
                reasoning_effort="high",
                extra_body={"thinking": {"type": "enabled"}},
                max_tokens=max_tokens
            )
            content = resp.choices[0].message.content
            print(f"  [AI返回长度] {len(content) if content else 0}")
            return robust_json_parse(content)
        except Exception as e:
            last_error = e
            print(f"  [AI生成失败，第{attempt+1}次尝试] {e}")
            if attempt < retry - 1:
                print("  [重试中…]")
    raise last_error


def load_male_blacklist():
    return load_json(MALE_BLACKLIST_FILE, {"characters": []})


def save_male_blacklist(data):
    save_json(MALE_BLACKLIST_FILE, data)


def load_unknown_counter():
    return load_json(UNKNOWN_COUNTER_FILE, {})


def save_unknown_counter(data):
    save_json(UNKNOWN_COUNTER_FILE, data)