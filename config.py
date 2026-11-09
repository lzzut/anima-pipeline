import os
import re
from prompt_sanitizer import sanitize_prompt_tags

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
BASE = os.path.dirname(os.path.abspath(__file__))
ANIMA_PROMPT_V2 = True
ANIMA_MATERIAL_CUTOFF = "2026-07"
ANIMA_PROMPT_EXPERIMENT = "baseline"
ANIMA_STAGED_ART_DIRECTION = True
ANIMA_CAMERA_DIRECTION = False
ANIMA_COMPOSITION_RESOLUTION = True
ANIMA_ENVIRONMENT_DIRECTION = True
ANIMA_FINAL_VISUAL_FOCUS = True
ANIMA_DESIGN_MAX_OUTPUT_TOKENS = 32000
ANIMA_SECOND_REVIEW_MODEL = ""
ANIMA_REVIEW_MAX_OUTPUT_TOKENS = 48000
ANIMA_REVIEW_RETRY_MAX_OUTPUT_TOKENS = 64000
ANIMA_FACT_MAX_OUTPUT_TOKENS = 48000
ANIMA_STABLE_MAX_OUTPUT_TOKENS = 32000
ANIMA_REPAIR_MAX_OUTPUT_TOKENS = 32000
ANIMA_SEMANTIC_REVIEW = "conditional"
ANIMA_PROMPT_MAX_CHARS = 16000
ANIMA_TOKENIZER_ROOT = os.environ.get("ANIMA_TOKENIZER_ROOT", "")
WORKFLOW_PATH = os.path.join(BASE, "workflow_api.json")
WORKFLOW_ANIMA_FLOW_PATH = os.path.join(BASE, "workflow_anima_flow.json")
CLIP_SKIP = -2
WORKFLOW_POOL = ["api", "anima_flow"]
ANIMA_UNET_INT8 = "Anima-2.9B-preview-v1_int8_convrot.safetensors"
ANIMA_UNET_NATIVE = "Anima-2.9B-preview-v1.safetensors"
ANIMA_UNET = ANIMA_UNET_INT8
WORKFLOW_SETTINGS = {
    "api": {"path": WORKFLOW_PATH, "unet": ANIMA_UNET, "steps": 50, "cfg": 5.0},
    "anima_flow": {"path": WORKFLOW_ANIMA_FLOW_PATH, "unet": ANIMA_UNET, "steps": 50, "cfg": 5.0},
}
GENERIC_FACE_TAGS = ()
EXTRA_NEGATIVE = (
    "cropped head, cut off headwear, out of frame, close-up, bad anatomy, bad proportions, extra fingers, "
    "missing fingers, fused fingers, mutated hands, missing limbs, malformed limbs, extra digits, fewer "
    "digits, watermark, signature, text, jpeg artifacts, lowres, worst quality, low quality, blurry, artist "
    "name"
)
EYE_NEGATIVE = "smudged eye, blurry eye, asymmetrical eyes, hair covering eye, eye covered by hair, one eye hidden"
EYE_LOCK = True
EYE_LOCK_WEIGHT = 1.25
EYE_WRONG_COLORS = (
    "purple eyes",
    "violet eyes",
    "pink eyes",
    "magenta eyes",
    "red eyes",
    "green eyes",
    "yellow eyes",
    "orange eyes",
    "amber eyes",
)
THEME_SCENE_RULES = {
    "kimono": {
        "keywords": ("和服", "kimono", "振袖", "furisode"),
        "keep": "a landscaped Japanese garden, a curved stone path beside a pond, layered maple foliage and a distant wooden veranda",
        "direction": (
            "Choose one thoughtfully composed setting for the kimono, with distinctive materials, spatial depth and "
            "light that support the garment and gesture. Stalls, vendor booths, food carts and makeshift market "
            "scenery are forbidden in every candidate. A festival mood may come from garden lanterns and seasonal "
            "planting without vendors. Suggested settings are alternatives, not elements to combine into one crowded "
            "scene."
        ),
        "scene_options": (
            "A pond garden with a curving stone path, maple branches and a receding wooden veranda.",
            "A refined traditional courtyard with timber columns, shoji screens and soft reflected garden light.",
            "A shrine approach with stone paving, mature trees and distant lanterns framing the figure.",
            "An engawa overlooking a seasonal garden, with layered foliage and a clear view toward the pond.",
        ),
        "forbid": (
            "\\bstalls?\\b",
            "\\bbooths?\\b",
            "\\byatai\\b",
            "\\b(?:street[ -]+)?vendors?\\b",
            "\\b(?:food|snack|market|festival)[ -]+(?:stands?|carts?)\\b",
            "\\b(?:night|street|open[ -]air|festival)[ -]+markets?\\b",
            "\\bmarketplaces?\\b",
            "\\bmakeshift[ -]+(?:sheds?|tents?|shops?)\\b",
        ),
        "negative": "market stalls, food stalls, vendor booths, street vendors, food carts, yatai, makeshift market",
    },
    "beach": {
        "keywords": ("泳装", "泳衣", "比基尼", "水着", "沙滩", "海边", "度假"),
        "keep": (
            "a sandy ocean beach, a curving wet shoreline with white surf washing onto the sand, open sea beyond the "
            "breakers and a small distant headland"
        ),
        "direction": (
            "Make the setting unmistakably a sandy ocean beach within the chosen crop. Describe a connected stretch of"
            " dry sand, the curved wet-sand edge with white breaking surf, and open sea beyond it; use visible "
            "portions of these connected features in a close crop. Keep sand and surf as the main setting, with a "
            "readable open-water expanse or sea horizon where the view permits. When theme.scene_today.setting is "
            "supplied, use its distant feature and sky as today's setting. Otherwise, whenever the view shows open "
            "sea, include by default one distant landform on the horizon named with a familiar noun, an island or a "
            "green hill, and a few shaped white clouds in the sky, such as cumulus clouds; place both in the frame. "
            "Coastal rocks, palm trees or dunes may frame one side of the beach in addition, but they never replace "
            "the distant landform and never replace sand and surf. If the weather or the brief rules out clouds or "
            "distant land, follow it. Avoid enclosing the figure in dark rock shelves, still tide pools or muddy "
            "shallow channels. Vary the beach shape and framing; do not default every character to the same low-tide "
            "rocky cove. Use clear land-water relationships and light rather than dense lists of sand grains or "
            "surface textures. Choose one setting; the examples are alternatives, not a checklist. Keep the figure "
            "prominent and preserve the intended crop. Do not add cities, buildings, pools or artificial floating "
            "particles."
        ),
        "scene_options": (
            (
                "A broad crescent sandy beach with a white surf line curving toward open ocean and a small green island on"
                " the horizon under shaped white clouds."
            ),
            (
                "A tree-shaded beach with dappled dry sand opening onto a bright wet-sand edge, gentle white surf, open "
                "ocean and a green hill on the far horizon beneath cumulus clouds."
            ),
            (
                "A sheltered sandy bay with palm trees at one edge, waves washing onto the sand, open sea and a low island"
                " on the horizon under scattered white clouds."
            ),
            (
                "A dune-backed beach with pale dry sand, a winding wet shoreline and foamy breakers facing the open sea, "
                "with a distant island and clouds in warm low light."
            ),
        ),
        "forbid": (
            "\\bcity\\b",
            "\\bskyline\\b",
            "\\bcastles?\\b",
            "\\bcathedral\\b",
            "\\bchurch\\b",
            "\\bspires?\\b",
            "\\btowers?\\b",
            "\\bbuildings?\\b",
            "\\barchitecture\\b",
            "\\bmetropolis\\b",
            "\\burban\\b",
            "\\bdowntown\\b",
            "\\bneon\\b",
            "\\brooftop\\b",
            "\\bindoors?\\b",
            "\\binterior\\b",
            "\\bstudio\\b",
            "\\bchateau\\b",
            "\\bpalace\\b",
            "swimming pool",
            "pool deck",
            "poolside",
            "floating bubbles?",
            "floating pearls?",
            "bubbles? catching the light",
            "(?:sparkling|glowing|floating|scattered) particles?",
            "floating orbs?",
            "glowing orbs?",
            "soap bubbles?",
        ),
        "negative": "city, castle, buildings, architecture, urban, indoor, swimming pool, floating bubbles, particles",
        "indoor": {
            "direction": (
                "Indoors this theme is set at an indoor swimming pool: keep a readable stretch of pool water visible "
                "within the chosen crop and include the familiar tag pool in the leading tag cluster of scene; the rest of"
                " the space is designed for this picture. The outdoor beach requirements (sand, surf, open sea, a distant "
                "landform and clouds) do not apply indoors."
            ),
            "allow": (
                "indoors",
                "interior",
                "swimming pool",
                "pool deck",
                "poolside",
                "buildings",
                "architecture",
            ),
            "negative": "city, castle, urban, floating bubbles, particles",
        },
    },
}
BEACH_EXPOSURE_NEGATIVE = "blown highlights, overexposure, overexposed skin, clipped whites"


def theme_scene_rule(theme):
    t = (theme or "").lower()
    for name, rule in THEME_SCENE_RULES.items():
        if any((k in t for k in rule["keywords"])):
            return (name, rule)
    return (None, None)


SCENE_ROTATION = True
SCENE_TIMES_ENABLED = ("晨", "昼", "昏", "夜")
SCENE_TIME_TAGS = {
    "晨": "morning, sunrise, sunlight",
    "昼": "day, sunlight",
    "昏": "sunset, orange sky, evening",
    "夜": "night, night sky",
}
SCENE_WEATHER_TAGS = {
    "晴": "blue sky",
    "雨": "rain, grey sky",
    "雪": "snowing, snowflakes, snow, grey sky",
}
SCENE_RAIN_CHANCE = 0.25
SCENE_RAIN_THEMES = ("和服", "旗袍", "制服", "季:春", "季:夏", "季:秋")
SCENE_SNOW_THEMES = ("圣诞", "季:冬")
SCENE_SNOW_CHANCE = 0.25
SCENE_TIME_TAGS_DIM = {"晨": "morning", "昼": "day", "昏": "evening", "夜": "night"}
SCENE_TIME_TAGS_INDOOR = {
    "晨": "morning, sunlight",
    "昼": "day, sunlight",
    "昏": "evening, sunset",
    "夜": "night",
}
SCENE_TIME_OPTIONS = 2
SCENE_ANGLES = {
    "平视": "straight-on",
    "仰视": "from below",
    "俯视": "from above",
    "侧面": "from side",
    "倾斜": "dutch angle",
}
SCENE_ANGLE_OPTIONS = 2
ANIMA_FOOTWEAR_CHECK = True
SCENE_POSTURES = {
    "站": "standing",
    "坐": "sitting",
    "倚靠": "leaning back or leaning forward",
    "走动": "walking",
    "半蹲": "squatting",
    "跪": "kneeling",
    "躺": "lying (on back, on side or on stomach)",
}
SCENE_POSTURE_OPTIONS = 2
SCENE_POSTURE_NEEDS = {"坐": "seat", "倚靠": "lean", "躺": "lie", "走动": "open"}
SCENE_CONTENT_SOURCE = "mixed"
SCENE_FIXED_ROUTE_CHANCE = 1 / 3
SCENE_INDOOR_CHANCE = 1 / 3
SCENE_INDOOR_ONLY_THEMES = ("护士",)
SCENE_OUTDOOR_ONLY_THEMES = ("春景", "夏景", "秋景", "冬景")
SCENE_THEME_TIMES = {
    "泳装": {"outdoor": "晨昼昏"},
    "比基尼": {"outdoor": "晨昼昏"},
    "运动": {"outdoor": "晨昼昏"},
    "浴衣": {"indoor": "昏夜", "outdoor": "昏夜"},
    "礼服": {"indoor": "昏夜", "outdoor": "昏夜"},
    "制服": {"indoor": "晨昼昏", "outdoor": "晨昼昏"},
}


def _sv(text, times, weather="", *, indoor=False, fixed_time=False, seasons=()):
    return {
        "text": text,
        "times": tuple(times),
        "weather": tuple(weather),
        "indoor": indoor,
        "fixed_time": fixed_time,
        "seasons": tuple(seasons),
    }


_BEACH_VARIANTS = (
    _sv(
        "Bay with an island: dry sand, curved wet sand and white surf, open sea to the horizon, a small green island on the horizon, cumulus clouds.",
        "晨昼昏",
        "晴",
    ),
    _sv(
        "Palm beach: dry sand, white surf and open sea, palm trees framing one side, a clean horizon.",
        "晨昼昏",
        "晴",
    ),
    _sv(
        "Rocky shore: sand beach with rocks at one side, waves breaking on the rocks, open sea to the horizon.",
        "晨昼昏",
        "晴",
    ),
    _sv(
        "Mountain bay: dry sand, white surf and open sea, a mountain range across the bay on the horizon.",
        "晨昼昏",
        "晴",
    ),
    _sv(
        "Summer storm cloud: dry sand, white surf and open sea, a towering cumulonimbus cloud over the horizon, seagulls in the distance.",
        "昼",
        "晴",
    ),
    _sv(
        (
            "Beach house: wooden floor, shade, bench, shaved ice, ocean, a roofed beach hut with wooden pillars, open "
            "at the front to the sand and white surf."
        ),
        "晨昼昏",
        "晴",
    ),
    _sv(
        "Indoor pool: indoors, swimming pool, pool, poolside, large windows.",
        "晨昼昏夜",
        indoor=True,
    ),
)
THEME_SCENE_VARIANTS = {
    "泳装": _BEACH_VARIANTS,
    "比基尼": _BEACH_VARIANTS,
    "和服": (
        _sv(
            "Pond garden: garden, pond, stone lantern, maple trees, a wooden veranda in the distance.",
            "晨昼昏",
            "晴雨",
        ),
        _sv(
            "Traditional courtyard: east asian architecture, sliding doors, shouji, garden light.",
            "晨昼昏夜",
            "晴雨",
        ),
        _sv("Shrine approach: shrine, torii, stone stairs, tall trees.", "晨昼昏", "晴"),
        _sv("Veranda: veranda, tatami, a view of the seasonal garden.", "晨昼昏夜", "晴雨"),
        _sv("Bamboo path: bamboo forest, path, soft light through bamboo.", "晨昼", "晴"),
        _sv(
            "Tatami room: indoors, tatami, shouji, sliding doors, wooden pillar.",
            "晨昼昏夜",
            indoor=True,
        ),
    ),
    "浴衣": (
        _sv(
            "Summer festival: summer festival, paper lantern, night sky.",
            "夜",
            "晴",
            fixed_time=True,
        ),
        _sv(
            "Riverside fireworks: fireworks, river, night, people in the distance.",
            "夜",
            "晴",
            fixed_time=True,
        ),
        _sv("Shrine stairs: shrine, torii, stone stairs, paper lantern.", "昏夜", "晴"),
        _sv("Goldfish scooping: goldfish scooping, paper lantern.", "夜", "晴", fixed_time=True),
        _sv("Bamboo night path: bamboo forest, lantern.", "夜", "晴", fixed_time=True),
        _sv(
            "Ryokan room: indoors, tatami, shouji, paper lantern, wind chime.", "昏夜", indoor=True
        ),
    ),
    "女仆": (
        _sv("Cafe: indoors, cafe, wooden floor, tea set.", "晨昼昏夜", indoor=True),
        _sv("Mansion parlor: indoors, fireplace, chandelier, curtains.", "昼昏夜", indoor=True),
        _sv("Garden tea party: garden, tea party, rose.", "晨昼", "晴"),
        _sv("Kitchen: indoors, kitchen, window.", "晨昼", indoor=True),
        _sv("Study: indoors, library, bookshelf, desk.", "昼昏夜", indoor=True),
    ),
    "制服": (
        _sv("Classroom: indoors, classroom, chalkboard, desk.", "晨昼昏", indoor=True),
        _sv("Hallway window: indoors, hallway, window, sunbeam.", "晨昼昏", indoor=True),
        _sv("Rooftop: rooftop, fence, cityscape in the distance.", "昼昏", "晴"),
        _sv("Library: indoors, library, bookshelf.", "昼昏", indoor=True),
    ),
    "护士": (
        _sv(
            "Hospital room: indoors, hospital bed, window, curtains, iv stand.",
            "晨昼昏夜",
            indoor=True,
        ),
        _sv("Infirmary: indoors, infirmary, desk.", "晨昼", indoor=True),
        _sv("Hospital hallway: indoors, hallway, hospital.", "昼夜", indoor=True),
        _sv("Hospital garden: outdoors, garden, bench, tree.", "晨昼", "晴"),
    ),
    "婚纱": (
        _sv("Church: indoors, church, stained glass, petals.", "昼昏", indoor=True),
        _sv("Garden arch: garden, arch, rose, petals.", "晨昼昏", "晴"),
        _sv("Lakeside: lake, tree.", "晨昼昏", "晴"),
        _sv("Flower field: sunflower field or meadow.", "昼昏", "晴"),
        _sv("Night balcony: balcony, city lights.", "夜", "晴", fixed_time=True),
    ),
    "礼服": (
        _sv(
            "Ballroom: indoors, chandelier, wooden floor, curtains, ballroom.",
            "夜",
            indoor=True,
            fixed_time=True,
        ),
        _sv("Piano hall: indoors, grand piano, curtains, chandelier.", "昼夜", indoor=True),
        _sv("Night terrace: balcony, night sky, city lights.", "夜", "晴", fixed_time=True),
        _sv("Red carpet: red carpet, light rays.", "夜", "", fixed_time=True),
        _sv("Fountain garden: fountain, garden, lamppost.", "昼昏夜", "晴"),
    ),
    "旗袍": (
        _sv("Rainy bridge: bridge, river.", "昼昏", "雨"),
        _sv("Chinese garden: pond, plum blossoms, east asian architecture.", "晨昼", "晴"),
        _sv("Pagoda view: pagoda, mountain, cloud.", "晨昼昏", "晴"),
        _sv("Night canal: canal, lantern.", "夜", "晴", fixed_time=True),
        _sv(
            "Teahouse: indoors, east asian architecture, round window, lattice, tea set.",
            "晨昼昏夜",
            indoor=True,
        ),
    ),
    "圣诞": (
        _sv(
            "Christmas living room: indoors, christmas tree, fireplace, gift box.",
            "昏夜",
            indoor=True,
        ),
        _sv("Snowy park: snow, park, lamppost, snowman.", "晨昼昏", "晴雪"),
        _sv("By the window: indoors, window, wreath.", "昼昏夜", indoor=True),
        _sv(
            "Ferris wheel at night: ferris wheel, christmas lights.", "夜", "晴雪", fixed_time=True
        ),
    ),
    "运动": (
        _sv("Running track: running track, track and field.", "晨昼昏", "晴"),
        _sv("Tennis court: tennis court, fence.", "晨昼", "晴"),
        _sv(
            "Gym: indoors, gym, basketball court, basketball hoop, bleachers, wooden floor, scoreboard, indoor lighting.",
            "昼",
            indoor=True,
        ),
        _sv("Riverside path: river, path, tree.", "晨昼昏", "晴"),
        _sv("Beach sand: beach, ocean.", "晨昼昏", "晴"),
    ),
    "季:春": (
        _sv("Cherry blossom park: cherry blossoms, park, petals, bench.", "晨昼昏", "晴"),
        _sv("Riverside cherry blossoms: river, cherry blossoms, bridge.", "晨昼昏夜", "晴雨"),
        _sv("Wisteria walk: wisteria, path.", "昼", "晴"),
        _sv(
            "Room by the window: indoors, window, curtains, petals, cherry blossoms outside the open window.",
            "晨昼昏",
            indoor=True,
        ),
    ),
    "季:夏": (
        _sv("Sunflower field: sunflower, cumulus clouds.", "昼昏", "晴"),
        _sv("Hydrangea path: hydrangea, path.", "昼", "雨"),
        _sv("Summer room: indoors, tatami, electric fan, wind chime, window.", "昼昏", indoor=True),
    ),
    "季:秋": (
        _sv("Ginkgo park: ginkgo tree, autumn leaves, park.", "晨昼昏", "晴"),
        _sv("Maple stone stairs: maple leaf, stone stairs, shrine.", "昼昏", "晴"),
        _sv("Riverside walk: riverbank, autumn leaves.", "昼昏", "晴"),
        _sv(
            "Autumn cafe: indoors, cafe, cup, steam, window, autumn leaves outside the window.",
            "昼昏夜",
            indoor=True,
        ),
    ),
    "季:冬": (
        _sv("Snowy forest: snow, forest, winter.", "晨昼", "晴雪"),
        _sv("Snowy shrine: snow, shrine, torii, stone stairs, tall trees.", "晨昼昏", "晴雪"),
        _sv("Snowy lakeside: snow, lake, tree, mountain.", "晨昼昏", "晴雪"),
        _sv("Kotatsu room: indoors, kotatsu, mandarin orange, tatami.", "昼昏夜", indoor=True),
    ),
}
ACTION_ROTATION = True
ANIMA_PERSONA_TRAITS = True
ACTION_RECENT_EXCLUDE = 3
ACTION_SHORTLIST = 4


def _act(text, tags, needs=(), themes=()):
    return {"text": text, "tags": tags, "needs": tuple(needs), "themes": tuple(themes)}


ACTION_VARIANTS = (
    _act("Hand in hair: one hand lifts to touch or tuck her hair.", "hand in own hair"),
    _act("Hands on hips: a confident stance with both hands on her hips.", "hands on own hips"),
    _act(
        "Arms behind back: a relaxed stance with her hands joined behind her back.",
        "arms behind back",
    ),
    _act("V sign: one hand makes a V sign near the face.", "v"),
    _act("Waving: one hand raised in a friendly wave.", "waving"),
    _act(
        "Looking back: her body faces away while she turns her head back over her shoulder toward the viewer (view rear, face visible).",
        "looking back, from behind",
    ),
    _act("Walking: caught mid-step while walking.", "walking", needs=("open",)),
    _act("Running: a light run with hair and clothes moving.", "running", needs=("open",)),
    _act("Jumping: a small joyful jump.", "jumping", needs=("open",)),
    _act("Sitting: seated naturally.", "sitting", needs=("seat",)),
    _act(
        "Sitting with crossed legs: seated with legs crossed.",
        "sitting, crossed legs",
        needs=("seat",),
    ),
    _act(
        "Hugging knees: seated with knees drawn up and arms around them.",
        "sitting, hugging own legs",
        needs=("seat",),
    ),
    _act("Leaning forward: leaning slightly toward the viewer.", "leaning forward"),
    _act(
        "Leaning on something: leaning against a nearby railing, wall or tree.",
        "leaning on object",
        needs=("lean",),
    ),
    _act("Squatting: a casual squat close to the ground.", "squatting"),
    _act("Kneeling: kneeling on one knee.", "on one knee"),
    _act("Holding a drink: holding a cup or bottle, about to drink.", "holding cup"),
    _act(
        "Holding an umbrella: holding an umbrella over her shoulder.",
        "holding umbrella",
        needs=("open", "umbrella"),
    ),
    _act(
        "Sheltering from the rain: standing under a roof edge or shelter, looking up at the falling rain.",
        "looking up",
        needs=("shelter", "rain"),
    ),
    _act(
        "Catching the rain: one hand held out, palm up, catching the falling rain.",
        "outstretched hand",
        needs=("open", "rain"),
    ),
    _act(
        "Holding a fan: holding a folding fan near the face.",
        "holding fan",
        themes=("和服", "浴衣", "旗袍", "季:夏"),
    ),
    _act(
        "Touching headwear: one hand touches her hat, headwear or hair ornament.",
        "hand on headwear",
    ),
    _act("Hand on cheek: resting her cheek on one hand.", "hand on own cheek"),
    _act("Stretching: stretching her arms up.", "stretching, arms up"),
)
EXPRESSION_VARIANTS = (
    {"text": "light smile", "tags": "light smile"},
    {"text": "bright smile", "tags": "smile, open mouth"},
    {"text": "grin", "tags": "grin"},
    {"text": "laughing", "tags": "laughing, :d"},
    {"text": "wink", "tags": "one eye closed, smile"},
    {"text": "playful tongue", "tags": "tongue out, :p"},
    {"text": "smug", "tags": "smug"},
    {"text": "blushing", "tags": "blush, light smile"},
    {"text": "embarrassed", "tags": "embarrassed, blush"},
    {"text": "peaceful", "tags": "closed eyes, light smile"},
    {"text": "dreamy", "tags": "half-closed eyes, parted lips"},
    {"text": "surprised", "tags": "surprised, :o"},
    {"text": "pout", "tags": "pout"},
    {"text": "head tilt", "tags": "head tilt, smile"},
)
ACTION_AFFORDANCE_WORDS = {
    "seat": (
        "sand",
        "beach",
        "bench",
        "veranda",
        "tatami",
        "stairs",
        "grass",
        "park",
        "garden",
        "cafe",
        "chair",
        "hospital bed",
        "rooftop",
        "riverbank",
        "field",
        "meadow",
        "gym",
        "library",
        "desk",
        "station",
        "lake",
        "fountain",
        "pond",
        "living room",
        "window",
    ),
    "lean": (
        "railing",
        "fence",
        "balcony",
        "window",
        "wall",
        "tree",
        "bridge",
        "lamppost",
        "bookshelf",
        "desk",
        "rock",
        "palm",
        "pillar",
        "arch",
        "piano",
        "vending machine",
        "storefront",
    ),
    "lie": (
        "sand",
        "beach",
        "grass",
        "meadow",
        "field",
        "lawn",
        "tatami",
        "bed",
        "bench",
        "poolside",
        "kotatsu",
        "veranda",
        "flower",
        "park",
    ),
    "shelter": (
        "bus stop",
        "shelter",
        "veranda",
        "convenience store",
        "storefront",
        "station",
        "beach hut",
    ),
}
SEASONAL_THEME_KEYWORDS = ("四季", "常装", "日常装", "季节装")
SHORT_PROMPT_ACTIVE = False
SHORT_PROMPT_FIELD_MAX = {
    "face_priority": 8,
    "outfit": 10,
    "eye_colors": 6,
    "core_features": 8,
    "appearance": 8,
}
SHORT_PROMPT_LIGHTING_MAX = 3
SHORT_PROMPT_SCENE_MAX = 2
SHORT_PROMPT_MAX_TAGS = 74
SHORT_PROMPT_OUTFIT_WEIGHT = 1.35
LINE_EXTRA_NEGATIVES = {
    "animagine_xl": (
        "logo, game logo, title, english text, chinese text, watermark, signature, text, yellow tint, sepia, color"
        " cast, oversaturated yellow, golden color cast, orange filter, asymmetrical eyes, eye out of socket, "
        "mismatched eye shape, deformed eyes, stiff pose, mannequin pose, flat background, fake background"
    ),
    "nova_xl": (
        "logo, game logo, title, english text, chinese text, watermark, signature, text, yellow tint, sepia, color"
        " cast, oversaturated yellow, golden color cast, orange filter, asymmetrical eyes, eye out of socket, "
        "deformed eyes, sitting, sitting on bench, full body, legs visible"
    ),
}
OUTFIT_SWAP_THEME_KEYWORDS = (
    "四季",
    "常装",
    "日常装",
    "季节装",
    "和服",
    "汉服",
    "制服",
    "水手服",
    "JK",
    "校服",
    "婚纱",
    "礼裙",
    "旗袍",
)
CHAR_BAN_LIST = ()
CHAR_OUTFIT_STRIP = {
    "hatsune_miku": (
        "detached sleeves",
        "teal necktie",
        "necktie",
        "teal hairband",
        "hairband",
        "square hair ornament",
    )
}
OUTFIT_STRIP_CLOTHING = (
    "long sleeves",
    "bridal gauntlets",
    "white gloves",
    "black gloves",
    "gloves",
    "neck ribbon",
    "bowtie",
    "jewelry",
    "collared shirt",
    "kneehighs",
    "thighhighs",
    "black skirt",
    "hair ribbon",
    "puff sleeves",
    "frilled sleeves",
    "cape",
    "sash",
    "tassel",
)
SCENE_ONLY_THEMES = ("背景", "外景")
CHAR_OFFICIAL_OUTFIT = {
    "furina_(genshin_impact)": (
        "navy blue beret with gold crown-shaped ornament, blue and white coat, blue and white dress, white gloves,"
        " blue gemstone pendant, black tights, blue and white boots"
    ),
    "raiden_shogun": "purple kimono, haori, purple obi bow, gold trim, purple flower hair ornament, gold hairpin, purple tassel earring",
}
CHAR_EYE_ANCHORS = {
    "furina_(genshin_impact)": "heterochromia, left eye light blue, right eye dark blue, detailed eyes",
    "raiden_shogun": "purple eyes, detailed eyes",
    "hatsune_miku": "aqua eyes, teal eyes, detailed eyes",
    "hu_tao_(genshin_impact)": "red eyes, flower-shaped pupils, detailed eyes",
    "march_7th_(honkai:_star_rail)": "blue eyes, pink eyes, heterochromia, detailed eyes",
}


def char_eye_anchor(name_en, simple=None):
    """返回该角色的瞳色锚定文本（优先 character_eyes.json，其次内置表）

    simple=True  → 去掉 left/right eye 细节（animagine 用这套更稳）
    simple=False → 保留完整左右明文（**nova 必须用这套**，否则异色瞳画不出来）
    """
    import json as _json
    import os as _os

    if simple is None:
        simple = CHAR_EYE_SIMPLE
    p = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "character_eyes.json")
    v = None
    if _os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = _json.load(f) or {}
            v = d.get(str(name_en))
        except Exception:
            v = None
    if not v:
        v = CHAR_EYE_ANCHORS.get(str(name_en))
    if v and simple:
        _parts = [x.strip() for x in str(v).split(",") if x.strip()]
        _kept = [x for x in _parts if not x.lower().startswith(("left eye", "right eye"))]
        return ", ".join(_kept) or str(v)
    return v


EYE_ENHANCE_WORKFLOWS = ()
SEASONAL_OUTFIT_FORCE = True
CHAR_BODY_ANCHOR_BY_CHAR = {
    "furina_(genshin_impact)": "mature female, adult, tall, slender, mature face",
    "hatsune_miku": "",
}
SDXL_AGE_NEGATIVE = (
    "(childlike proportions:1.2), (oversized head:1.15), (baby face:1.15), (round face:1.1), (youthful "
    "face:1.1), (small facial features:1.1), (flat face:1.1)"
)
ANIMAGINE_BODY_PROFILES = {
    "adult_mature": ("mature female, adult, tall, slender, mature face", "adult"),
    "adult_slim": ("adult woman, slender, mature face", "adult"),
    "adult_petite": ("petite adult woman, slender, young adult", "adult_petite"),
    "teen": ("teenager, young woman, slender", "teen"),
    "child": ("child, petite, small", "child"),
    "nonhuman": ("", "none"),
}
CHAR_BODY_NEG_BY_CHAR = {"furina_(genshin_impact)": "adult", "hatsune_miku": "teen"}
SDXL_BODY_NEGATIVE_PETITE = "child, loli, chibi, childlike proportions, oversized head"
SDXL_AGE_NEGATIVE_PETITE = "(baby face:1.1), (childlike face:1.1)"
SDXL_TEEN_NEGATIVE = "child, loli, chibi, toddler, childlike proportions, oversized head"
SDXL_CHILD_NEGATIVE = "mature female, adult, tall, curvy, wide hips, large breasts"


def animagine_body_profile(body_type="", name_en="", body_text=""):
    """返回 (正向体型锚点, 负面类型, 归一化 body_type)。

    2026-10-21：body_type 由 LLM 按官方设定输出；缺失时从 body 文本兜底。
    per-char 覆盖优先（Furina=已验证的 5 词成年锚，Miku=空=不补成年）。
    """
    bt = str(body_type or "").strip().lower()
    if bt not in ANIMAGINE_BODY_PROFILES:
        _b = str(body_text or "").lower()
        if any((k in _b for k in ("child", "loli", "toddler", "kodomo"))):
            bt = "child"
        elif any((k in _b for k in ("teen", "teenager", "adolescent"))):
            bt = "teen"
        elif any(
            (
                k in _b
                for k in ("petite", "small body", "small frame", "short stature", "short height")
            )
        ):
            bt = "adult_petite"
        elif "mature" in _b or "tall" in _b:
            bt = "adult_mature"
        else:
            bt = "adult_slim"
    if str(name_en) in (CHAR_BODY_ANCHOR_BY_CHAR or {}):
        anchor = CHAR_BODY_ANCHOR_BY_CHAR[str(name_en)] or ""
    else:
        anchor = ANIMAGINE_BODY_PROFILES[bt][0]
    neg = (CHAR_BODY_NEG_BY_CHAR or {}).get(str(name_en)) or ANIMAGINE_BODY_PROFILES[bt][1]
    return (anchor, neg, bt)


CHAR_EYE_SIMPLE = True
SDXL_CROP_FRAMING = (
    "(upper body:1.35), three-quarter view, shallow depth of field, blurred background"
)
SDXL_FRAMING_POSITIVE = (
    "(upper body:1.35), (portrait:1.2), three-quarter view, face focus, head and shoulders"
)
SDXL_FRAMING_NEGATIVE = "full body, full-length, wide shot, legs visible, feet visible, standing legs, distant view, zoomed out, full body shot"
OUTFIT_SWAP_WEIGHT = 1.35
THEME_CTX = ""
OUTFIT_SWAP_NEGATIVE = (
    "official costume, character's default outfit, signature outfit, white gloves, gold trim coat, blue coat, "
    "frilled collar, theatrical costume, uniform coat"
)
OUTFIT_SWAP_COVER = (
    "oversized wool coat closed to the neck, thick knit scarf wrapped around neck covering the chest, long "
    "sleeves covering arms, fully clothed, layered winter outfit"
)
OUTFIT_SWAP_WEIGHT_HARD = 1.5


def is_outfit_swap_theme(theme):
    t = str(theme or "")
    return any((k in t for k in OUTFIT_SWAP_THEME_KEYWORDS))


SEASONAL_WORKFLOWS = ("api", "anima_flow", "animagine_xl", "nova_xl")
SEASONAL_OVERRIDE = None
SCENE_DETAILS = {
    "四季": "layered foreground foliage, path with stone paving, distant buildings and lamp posts, bokeh depth of field, natural perspective",
    "常装": "city street with storefronts and railings, soft bokeh, natural perspective",
    "泳装": "shallow water reflecting sunlight, distant shoreline, sand with footprints, bright sky with clouds, bokeh",
    "浴衣": "festival stalls with paper lanterns in the background, night sky, warm lantern glow, shallow depth of field",
    "和服": "traditional garden with stone lantern and wooden fence, soft daylight, layered foliage, bokeh",
    "制服": "classroom or school corridor with windows and desks, natural light, shallow depth of field",
    "女仆": "cafe interior with warm lamps and wooden furniture, soft bokeh, natural perspective",
    "圣诞": "festive street with string lights, decorated trees, warm glow, bokeh",
    "婚纱": "church or garden venue with floral arch and soft light, bokeh, natural perspective",
    "旗袍": "old town street with hanging lanterns, wooden railings, soft daylight, bokeh",
    "礼服": "ballroom with chandeliers and soft reflections, warm light, bokeh",
    "运动": "outdoor court or track with fence and distant trees, bright daylight, natural perspective",
}
SEASONAL_OVERRIDE_BY_LINE = {
    "animagine_xl": {
        "scene": [
            (
                "autumn park path with golden ginkgo and orange maple trees, fallen leaves on stone paving, distant "
                "benches and lamp posts, soft bokeh background"
            ),
            "tree-lined avenue in autumn, warm sunlight through yellow leaves, scattered maple leaves on the ground, shallow depth of field",
            "riverside promenade in autumn, orange and gold foliage, calm water reflection, fallen leaves drifting",
            "quiet garden corner in autumn, wooden bench and stone lantern, maple leaves floating, soft diffused light",
        ],
        "pose": [
            "standing with a slight turn, one hand touching hair",
            "walking along the path, mid-stride, scarf swaying",
            "leaning against a wooden bench, arms loosely crossed",
            "sitting on the bench edge, one leg crossed over the other, hands on lap",
            "reaching up to catch a falling leaf, looking upward",
        ],
        "lighting": "soft afternoon sunlight with gentle rim light, natural skin tone",
        "outfit": (
            "cream cable-knit sweater, red knit scarf loosely draped on shoulders, brown plaid pleated skirt, black "
            "tights, brown lace-up boots, beige beret, tan leather shoulder bag"
        ),
    },
    "nova_xl": {
        "scene": [
            "autumn park with golden ginkgo trees, fallen leaves on the ground, soft bokeh background",
            "tree-lined street in autumn, warm sunlight through yellow leaves, shallow depth of field",
            "autumn garden with stone paving, scattered maple leaves, distant buildings",
        ],
        "pose": [
            "standing with a slight turn, one hand on hip",
            "walking forward, looking at viewer, scarf flowing",
            "sitting sideways on a bench, hands together on lap",
        ],
        "lighting": "soft afternoon sunlight, natural skin tone",
    },
}
SEASONAL_OUTFIT = {
    "春": {
        "outfit": "layered light cardigan over a long-sleeve blouse, pleated skirt, ankle socks, loafers, small woven shoulder bag, delicate ribbon detail",
        "scene": "spring park with cherry blossoms, soft pink petals falling, gentle sunlight, fresh green grass",
        "weighted": "(cherry blossom petals:1.2), (soft pink petals:1.15), (fresh green grass:1.1)",
        "pose": (
            "sitting sideways on a park bench, knees together, both feet resting on the ground, ankles slightly "
            "crossed, one hand touching hair, three-quarter view"
        ),
        "negative": "autumn leaves, snow, bare trees, swimsuit, swimwear",
    },
    "夏": {
        "outfit": "short-sleeve cotton shirt, light pleated skirt, straw hat, sandals, thin tote bag, rolled-up sleeves, fresh light fabric",
        "scene": "bright summer street, dappled shade under green trees, clear blue sky, cicada ambience",
        "weighted": "(strong summer sunlight:1.15), (dappled leaf shadows:1.15), (clear blue sky:1.1)",
        "pose": "walking forward with a light step, three-quarter view, one hand holding a cold drink, hair swaying in a breeze",
        "negative": "autumn leaves, snow, wool coat, swimsuit, swimwear",
    },
    "秋": {
        "outfit": (
            "cream chunky cable-knit sweater with visible knit texture, dark red wool scarf, plaid skirt, black "
            "tights, brown leather lace-up boots, beret, leather shoulder bag"
        ),
        "scene": "autumn park with golden ginkgo and orange maple trees, fallen yellow leaves on the path, wooden bench, warm golden afternoon light",
        "weighted": "(golden ginkgo trees:1.25), (orange red maple leaves:1.25), (fallen yellow leaves on the ground:1.2), (warm golden afternoon light:1.15)",
        "pose": (
            "sitting sideways on a wooden bench, knees together, both feet resting on the ground, ankles slightly "
            "crossed, slight lean forward, one hand holding a paper coffee cup, the other hand resting on the bench, "
            "three-quarter view"
        ),
        "negative": (
            "green leaves, cherry blossoms, spring, green grass, blue flowers, hydrangea, blue hydrangea, morning "
            "glory, sunflower, lotus, swimsuit, swimwear"
        ),
    },
    "冬": {
        "outfit": "layered wool coat over turtleneck sweater, knit scarf, thick black tights, winter boots, earmuffs, gloves, textured wool fabric",
        "scene": "winter street with bare trees, soft falling snow, cold pale blue sky, warm visible breath",
        "weighted": "(soft falling snow:1.25), (bare winter trees:1.15), (cold pale blue sky:1.1)",
        "pose": "standing with hands in coat pockets, slight three-quarter turn, shoulders drawn together against the cold, visible breath",
        "negative": "green leaves, cherry blossoms, autumn leaves, swimsuit, swimwear",
    },
}
SEASONAL_DESIGN_RULES = (
    "layered outfit, visible fabric texture, knit or wool material, scarf, bag, coordinate accessories, "
    "colour-coordinated palette, bag carried on the shoulder, accessories worn properly, both hands naturally "
    "occupied"
)
SEASONAL_POSE_NEGATIVE = (
    "plain outfit, flat colour, school uniform, standing straight, stiff pose, front view, symmetrical "
    "composition, blank expression, empty background, oversized hat, floating hat, hat held above the head, "
    "object merged with hand, fused legs, merged legs, missing knee, distorted knees, twisted legs, malformed "
    "ankles, bad leg proportions, extra legs, missing legs, conjoined legs"
)
PROMPT_RICHNESS = (
    (
        "lighting",
        ("rim light", "key light", "bounce light", "backlit"),
        370,
        (
            "lighting direction consistent with the scene, soft ambient bounce light, rim light from the main light "
            "source, contact shadows grounding the character"
        ),
    ),
    (
        "depth",
        ("depth of field", "bokeh", "background blur"),
        260,
        "shallow depth of field, crisp focus on the face and upper body, gentle graduated background blur, soft sparkling bokeh highlights",
    ),
    (
        "body",
        (),
        260,
        "natural body proportions consistent with the official character design, correct anatomy, soft skin shading, graceful posture",
    ),
    (
        "expression",
        (),
        200,
        "lively expressive eyes, gentle natural smile, subtle blush, relaxed brows",
    ),
    (
        "outfit",
        ("fabric texture", "knit", "wool", "stitching", "trim"),
        380,
        "visible fabric texture, layered clothing details, neat stitching and trim",
    ),
    (
        "composition",
        ("negative space", "headroom", "subject placement"),
        320,
        "balanced negative space, headroom preserved, clear subject placement, coherent foreground and background separation",
    ),
    (
        "appearance",
        ("detailed eyes", "detailed face", "long eyelashes", "gradient hair"),
        420,
        "delicately rendered facial features, detailed eyes, soft skin shading, distinct hair strands with subtle highlights",
    ),
)
PROMPT_RICHNESS_COMPOSITION_DYNAMIC = (
    "composition",
    ("rule-of-thirds", "rule of thirds", "negative space"),
    320,
    "rule-of-thirds placement, balanced negative space, headroom preserved, steady eye-level angle",
)
THEME_GATE_MIN_POSTS = 150
THEME_GATE_MIN_RATIO = 0.03
THEME_GATE_SWAP = False
THEME_TAG_MAP = {
    "泳装": "swimsuit",
    "比基尼": "bikini",
    "和服": "kimono",
    "浴衣": "yukata",
    "女仆": "maid",
    "圣诞": "christmas",
    "婚纱": "wedding dress",
    "护士": "nurse",
    "制服": "school uniform",
    "运动": "sportswear",
    "旗袍": "cheongsam",
    "礼服": "evening dress",
    "四季常装": "casual",
}
THEME_ALIASES = {"泳衣": "泳装", "常装": "四季常装"}


def canonical_theme(theme):
    """把主题别名归一到 THEME_TAG_MAP 的规范 key。"""
    t = str(theme or "").strip()
    return THEME_ALIASES.get(t, t)


BANNED_THEMES = ("兔女郎", "bunny girl")
BANNED_THEME_NEGATIVE = "bunny girl, bunny suit, playboy bunny, bunny ears, leotard"
SMOKING_NEGATIVE = "cigarette, smoking, cigar, holding cigarette"
ANIMA_BACKGROUND_TAGS = "detailed background"
ANIMA_BACKGROUND_NEGATIVE = "simple background"
THEME_CANDIDATES = (
    "japanese clothes",
    "kimono",
    "swimsuit",
    "school uniform",
    "maid",
    "christmas",
    "wedding dress",
    "yukata",
    "casual",
)
IDENTITY_JUDGE_MAX_TOKENS = 2500
MODEL_KEY = {
    "api": "Anima-2.9B",
    "anima_flow": "Anima-2.9B",
    "animagine_xl": "AnimagineXL4",
    "nova_xl": "NovaAnimeXL",
}


def model_key(workflow):
    return MODEL_KEY.get(workflow, workflow)


REF_TEMPLATE = True
PROMPT_TEMPLATE_VERSION = "v3"
V3_FIELD_MAX = {
    "face_priority": 6,
    "eye_colors": 4,
    "core_features": 6,
    "appearance": 8,
    "grounded_appearance": 8,
    "hybrid_features": 12,
    "outfit": 10,
    "body": 6,
    "expression": 4,
    "pose": 4,
}
V3_SCENE_MAX = 2
V3_LIGHTING_MAX = 4
V3_MAX_TAGS = 120
V3_TAIL = (
    "detailed background, depth of field, natural skin texture, sharp focus, soft natural lighting"
)
V3_TAIL_DYNAMIC = "cinematic composition, dynamic angle, detailed background, depth of field, natural skin texture, sharp focus, soft natural lighting"
V3_ADD_DIGNITY = True
V3_FULL_ANATOMY = True
PROMPT_QUALITY_V2 = False
CHARACTER_PORTRAYAL_REFINEMENT = False
ANIMA_SOURCE_EVIDENCE = True
ANIMA_LEGACY_IDENTITY_BACKFILL = False
ANIMA_APPEARANCE_ENRICHMENT = False
ANIMA_CHARACTER_CONSISTENCY = True
ANIMA_FEATURE_RETENTION = True
ANIMA_EXPRESSION_POLICY = True
ANIMA_FRAMING_REFINEMENT = True
ANIMA_FRAMING_CONTENT = True
ANIMA_COMPLETE_HEAD_PRIORITY = False
STABLE_CANDIDATE_POSES = True
ANIMA_SAME_PROMPT_SEEDS = True
MAKEUP_SOFTEN = True
MAKEUP_NEGATIVE = "thick eyeliner, overdrawn lips"
_MAKEUP_COLORS = (
    "purple",
    "violet",
    "plum",
    "wine",
    "burgundy",
    "red",
    "crimson",
    "rose",
    "pink",
    "magenta",
    "coral",
    "peach",
    "orange",
    "gold",
    "brown",
    "nude",
    "blue",
    "teal",
    "green",
)


def _soften_makeup_tag(tag):
    """Return a softened makeup tag, or None if this tag is not makeup."""
    t = str(tag or "").strip()
    low = t.lower()
    color = next((c for c in _MAKEUP_COLORS if re.search("\\b" + c + "\\b", low)), "")
    if "eyeshadow" in low:
        return f"light {color} eyeshadow" if color else "light eyeshadow"
    if "eyeliner" in low:
        return f"soft {color} eyeliner" if color else "soft eyeliner"
    if "lipstick" in low or "lip gloss" in low or re.search("\\blips?\\b", low):
        return f"light {color} lips" if color else "light lips"
    return None


BODY_SOFTEN = False


def soften_makeup(structured):
    """Soften LLM-written makeup in-place for every character.

    Keeps canonical colors, but replaces heavy wording/weights with
    'subtle <color> lips' / 'soft <color> eyeshadow'.
    Returns True if anything changed.
    """
    if not isinstance(structured, dict):
        return False
    changed = False
    for field in (
        "face_priority",
        "appearance",
        "core_features",
        "expression",
        "expression_priority",
    ):
        val = structured.get(field)
        if not isinstance(val, str) or not val.strip():
            continue
        out = []
        for tag in [x.strip() for x in val.split(",") if x.strip()]:
            soft = _soften_makeup_tag(tag)
            if soft:
                out.append(soft)
                changed = True
            else:
                out.append(tag)
        structured[field] = ", ".join(out)
    if changed:
        neg = str(structured.get("negative") or "").strip()
        if "heavy makeup" not in neg.lower():
            structured["negative"] = (neg + ", " + MAKEUP_NEGATIVE).strip(", ")
    return changed


REF_QUALITY = "masterpiece, best quality, highres, absurdres, year 2026, newest, very aesthetic, extremely detailed, intricate details"
REF_ARTISTS = "@ciloranko, (@mika pikazo:0.7), (@wlop:0.5)"
REF_ANATOMY = (
    "perfect anatomy, correct anatomy, detailed hands, five fingers, realistic arm structure"
)
REF_DIGNITY = "dignified expression, elegant, natural adult face, half-closed eyes, piercing gaze"
REF_DIGNITY_V2 = "natural facial expression, calm, composed"
ANIMA_DYNAMIC_NEGATIVE = "passport photo, stiff pose, mannequin pose, flat background, fake background, pasted background, no contact shadows, floating background"
ANIMA_DYNAMIC_NEGATIVE_DYNAMIC = (
    "centered composition, symmetrical composition, steady eye-level, front view, passport photo, stiff pose, "
    "mannequin pose, static pose, flat background, fake background, pasted background, no contact shadows, "
    "floating background"
)
ANIMA_INTEGRATION_NEGATIVE = (
    "pasted character, cutout, sticker, floating character, mismatched lighting, inconsistent shadows, no cast"
    " shadow, composited, green screen, disconnected from background, wrong perspective scale"
)
REF_TAIL = (
    "cinematic composition, dynamic angle, soft lighting, lens flare, detailed background, depth of field, "
    "water droplets on skin, wet hair, sunlight through hair"
)
REF_TAIL_V2 = "cinematic composition, dynamic angle, natural soft lighting, detailed background, depth of field, sharp focus, natural skin texture"
REF_TAIL_WET = "water droplets on skin, wet hair"
REF_TAIL_LITE = "delicate skin, detailed skin, beautiful detailed eyes, intricate details, sharp focus, best quality, soft lighting, depth of field"
REF_ANATOMY_LITE = "perfect anatomy, correct anatomy, detailed hands, five fingers"
SDXL_SKIN_NEGATIVE = (
    "yellow skin, orange skin tone, warm color cast, jaundice, oversaturated skin, plastic skin"
)
SDXL_NEUTRAL_LIGHT = "soft natural lighting, natural skin tone"
SDXL_BODY_NEGATIVE = (
    "child, loli, chibi, petite, small body, short stature, childlike proportions, oversized head"
)
PROMPT_CHANNELS = ("stable",)
PROMPT_CHANNEL_DEFAULT = "stable"
PROMPT_CHANNEL_PROFILES = {
    "dynamic": {
        "llm_directive": "dynamic",
        "fix_rewrite": "dynamic",
        "v3_tail_attr": "V3_TAIL_DYNAMIC",
        "v3_composition_drop_shots": False,
        "v3_beach_drop_soft_light": True,
        "dynamic_negative_attr": "ANIMA_DYNAMIC_NEGATIVE_DYNAMIC",
        "richness_composition_attr": "PROMPT_RICHNESS_COMPOSITION_DYNAMIC",
        "seasonal_upper_body_pose": True,
        "outfit_swap_keep_identity": False,
        "dressup_conflict_cleanup": True,
        "beach_lighting": True,
        "fit_pose_to_framing": False,
        "simplify_hand_pose": False,
    },
    "stable": {
        "llm_directive": "stable",
        "fix_rewrite": "stable",
        "v3_tail_attr": "V3_TAIL",
        "v3_composition_drop_shots": True,
        "v3_beach_drop_soft_light": True,
        "dynamic_negative_attr": "ANIMA_DYNAMIC_NEGATIVE",
        "richness_composition_attr": None,
        "seasonal_upper_body_pose": False,
        "outfit_swap_keep_identity": True,
        "dressup_conflict_cleanup": True,
        "beach_lighting": True,
        "fit_pose_to_framing": True,
        "simplify_hand_pose": True,
    },
}


def prompt_channel_profile(channel=None):
    """通道配置；None → 稳定版。未知通道名直接报错，避免拼写错误悄悄走错版本。"""
    key = PROMPT_CHANNEL_DEFAULT if channel is None else channel
    if key not in PROMPT_CHANNEL_PROFILES:
        raise KeyError(f"未知提示词通道：{channel!r}")
    return PROMPT_CHANNEL_PROFILES[key]


def prompt_channel_const(channel, key):
    """按通道取常量（profile 里存的是常量名）；未配置返回 None。"""
    name = prompt_channel_profile(channel).get(key)
    return globals().get(name) if name else None


def prompt_richness_for(channel=None):
    """该通道的 PROMPT_RICHNESS：灵动版把构图那一行换回旧条目，其余与稳定版相同。"""
    repl = prompt_channel_const(channel, "richness_composition_attr")
    if not repl:
        return PROMPT_RICHNESS
    return tuple((repl if row[0] == repl[0] else row for row in PROMPT_RICHNESS))


def active_prompt_channels():
    """生产通道：去重保序，未知名报错。"""
    out = []
    for ch in PROMPT_CHANNELS or (PROMPT_CHANNEL_DEFAULT,):
        prompt_channel_profile(ch)
        if ch not in out:
            out.append(ch)
    return tuple(out)


def build_reference_prompt(
    structured,
    name_en,
    series_en,
    theme=None,
    framing=None,
    compact=False,
    extra_fields=(),
    channel=None,
):
    """Implementation details: see docs/ARCHITECTURE.md."""
    from framing_content import prompt_framing

    framing = prompt_framing(framing)
    st = structured or {}
    compact = bool(compact or SHORT_PROMPT_ACTIVE)
    esc = (name_en or "").replace("_", " ").replace("(", "\\(").replace(")", "\\)")
    plain = (name_en or "").replace("_", " ")
    parts = [REF_QUALITY, "1girl, solo"]
    ch = ", ".join((x for x in (esc, plain, series_en or "") if x))
    if ch:
        parts.append(ch)
    if framing:
        parts.insert(2, str(framing))
    if str(PROMPT_TEMPLATE_VERSION).lower() == "v3":
        _chp = prompt_channel_profile(channel)
        _order = (
            "face_priority",
            "eye_colors",
            "hybrid_features",
            "outfit",
            "body",
            "expression",
            "expression_priority",
            "pose",
        )
        _content_spec = st.get("_framing_content_spec") or {}
        if CHARACTER_PORTRAYAL_REFINEMENT or _content_spec:
            _order = (
                "face_priority",
                "eye_colors",
                "expression_priority",
                "expression",
                "hybrid_features",
                "outfit",
                "body",
                "pose",
            )
        for k in _order:
            v = str(st.get(k) or "").strip()
            if not v:
                continue
            cap = _content_spec.get("field_budgets", {}).get(k, V3_FIELD_MAX.get(k, 4))
            parts.append(
                v
                if _content_spec
                else ", ".join([x.strip() for x in v.split(",") if x.strip()][:cap])
            )
        for k in ("scene_foreground", "scene_midground", "scene_background"):
            v = str(st.get(k) or "").strip()
            if v:
                _scene_cap = _content_spec.get("scene_budget", V3_SCENE_MAX)
                parts.append(
                    v
                    if _content_spec
                    else ", ".join([x.strip() for x in v.split(",") if x.strip()][:_scene_cap])
                )
        for k, cap in (("lighting", V3_LIGHTING_MAX), ("composition", 3), ("depth", 2)):
            v = str(st.get(k) or "").strip()
            if v:
                if _content_spec:
                    from framing_content import split_prompt_tags

                    _vals = split_prompt_tags(v)
                else:
                    _vals = [x.strip() for x in v.split(",") if x.strip()]
                if k == "composition" and _chp["v3_composition_drop_shots"]:
                    _shot_tags = {
                        "full body",
                        "cowboy shot",
                        "upper body",
                        "close-up",
                        "portrait",
                        "medium shot",
                        "wide shot",
                    }
                    _vals = [x for x in _vals if x.lower() not in _shot_tags]
                if _vals:
                    parts.append(", ".join(_vals if _content_spec else _vals[:cap]))
        parts.append(REF_ANATOMY_LITE)
        if V3_FULL_ANATOMY:
            parts.append("realistic arm structure")
        _v3_theme = str(theme or "")
        _v3_wet = any(
            (
                k in _v3_theme
                for k in ("泳装", "泳衣", "比基尼", "水着", "沙滩", "海边", "雨", "湿身")
            )
        )
        _v3_beach = any(
            (k in _v3_theme for k in ("泳装", "泳衣", "比基尼", "水着", "沙滩", "海边", "度假"))
        )
        _v3_tail = prompt_channel_const(channel, "v3_tail_attr")
        if _v3_beach and _chp["v3_beach_drop_soft_light"]:
            _v3_tail = _v3_tail.replace(", soft natural lighting", "")
        parts.append(_v3_tail + (", water droplets on skin, wet hair" if _v3_wet else ""))
        if (
            V3_ADD_DIGNITY
            and (not CHARACTER_PORTRAYAL_REFINEMENT)
            and (not st.get("_expression_policy"))
            and (str(st.get("body_type") or "").lower() not in ("child", "teen"))
        ):
            parts.append(REF_DIGNITY)
        return sanitize_prompt_tags(parts, st, theme=theme, framing=framing, max_tags=V3_MAX_TAGS)
    if compact:
        pass
        _order = (
            "face_priority",
            "expression_priority",
            "expression",
            "outfit",
            "eye_colors",
            "core_features",
            "appearance",
        )
        for k in _order:
            v = str(st.get(k) or "").strip()
            if not v:
                continue
            _ls = [x.strip() for x in v.split(",") if x.strip()]
            _txt = ", ".join(_ls[: SHORT_PROMPT_FIELD_MAX.get(k, 8)])
            if k == "outfit" and _txt:
                _txt = f"wearing ({_txt}:{SHORT_PROMPT_OUTFIT_WEIGHT})"
            parts.append(_txt)
        lt = str(st.get("lighting") or "").strip()
        if lt:
            parts.append(
                ", ".join(
                    [x.strip() for x in lt.split(",") if x.strip()][:SHORT_PROMPT_LIGHTING_MAX]
                )
            )
        sc = " ".join((str(st.get(k) or "") for k in ("scene_background", "scene_midground")))
        if sc.strip() and SHORT_PROMPT_SCENE_MAX > 0:
            _sc = [x.strip() for x in sc.split(",") if x.strip()][:SHORT_PROMPT_SCENE_MAX]
            if _sc:
                parts.append(", ".join(_sc))
        parts.append(REF_ANATOMY_LITE)
        parts.append(REF_TAIL_LITE)
        _joined = ", ".join((p for p in parts if p))
        if "heterochromia" in _joined.lower():
            _eye_re = re.compile(
                (
                    "(?i)^(light |dark |pale |deep |bright "
                    ")?(red|blue|green|purple|violet|aqua|teal|yellow|orange|pink|gold|amber|grey|gray|brown|heterochromia) "
                    "eyes?$"
                )
            )
            _out = []
            for _x in _joined.split(","):
                _t2 = _x.strip()
                if not _t2:
                    continue
                if _eye_re.match(_t2) and "heterochromia" not in _t2.lower():
                    continue
                _out.append(_t2)
            _joined = ", ".join(_out)
        _seen, _uniq = (set(), [])
        for _x in _joined.split(","):
            _k = _x.strip().lower()
            if _k and _k not in _seen:
                _seen.add(_k)
                _uniq.append(_x.strip())
        return ", ".join(_uniq[:SHORT_PROMPT_MAX_TAGS])
    try:
        from booru_client import appearance_tags

        _feat_cap = 12 if PROMPT_QUALITY_V2 else 18
        feats = [t.replace("_", " ") for t in appearance_tags(name_en, sample=40) or []][:_feat_cap]
        if feats:
            parts.append(", ".join(feats))
    except Exception:
        pass
    for k in ("face_priority", "appearance"):
        v = str(st.get(k) or "").strip()
        if v:
            parts.append(v)
    if "body" not in (extra_fields or ()):
        _bv = str(st.get("body") or "").strip()
        if _bv:
            parts.append(_bv)
    for k in ("outfit",):
        v = str(st.get(k) or "").strip()
        if v:
            parts.append(v)
    for k in extra_fields or ():
        v = str(st.get(k) or "").strip()
        if not v:
            continue
        if k == "composition" and framing:
            _f0 = str(framing).split(",")[0].strip().lower()
            _keep = []
            for _x in v.split(","):
                _xl = _x.strip().lower()
                if (
                    _xl in ("cowboy shot", "full body", "upper body", "close-up", "portrait")
                    and _xl != _f0
                ):
                    continue
                if _xl:
                    _keep.append(_x.strip())
            v = ", ".join(_keep)
        if v:
            parts.append(v)
    parts.append(REF_ANATOMY)
    _expr_v = str(st.get("expression") or "").strip()
    _bt = str(st.get("body_type") or "").strip().lower()
    _skip_dignity = _bt in ("child", "teen")
    if _expr_v:
        parts.append(_expr_v)
        if not PROMPT_QUALITY_V2 and (not _skip_dignity):
            parts.append(REF_DIGNITY if REF_DIGNITY.split(",")[0] not in parts[-1] else "")
    elif not _skip_dignity:
        parts.append(REF_DIGNITY_V2 if PROMPT_QUALITY_V2 else REF_DIGNITY)
    for k in ("pose", "scene_foreground", "scene_midground", "scene_background", "lighting"):
        v = str(st.get(k) or "").strip()
        if v:
            parts.append(v)
    _theme_s = str(theme or "")
    _wet_theme = any(
        (k in _theme_s for k in ("泳装", "泳衣", "比基尼", "水着", "沙滩", "海边", "雨", "湿身"))
    )
    if PROMPT_QUALITY_V2:
        _tail_v2 = REF_TAIL_V2 + (", " + REF_TAIL_WET if _wet_theme else "")
        parts.append(_tail_v2)
    else:
        parts.append(REF_TAIL_LITE if "四季" in _theme_s else REF_TAIL)
    _theme = str(theme or "")
    _is_swim = any(
        (k in _theme for k in ("泳装", "泳衣", "比基尼", "水着", "沙滩", "海边", "度假"))
    )
    _conflict = (
        "bridal gauntlets",
        "long sleeves",
        "gloves",
        "neck ribbon",
        "hair ribbon",
        "jewelry",
        "bow",
        "kimono",
        "japanese clothes",
        "hakama",
        "obi",
        "frilled sleeves",
        "boots",
        "thighhighs",
        "sleeves",
        "armor",
        "pauldron",
    )
    _skin = "delicate skin, detailed skin, beautiful detailed eyes"
    _body = "bare shoulders, midriff, navel, collarbone"

    def _clean(text):
        _segs = []
        for _seg in str(text or "").split(","):
            _segs.append(_seg if "@" in _seg else re.sub("\\(([^()]*?):[\\d.]+\\)", "\\1", _seg))
        t = ",".join(_segs)
        if _is_swim:
            for _w in _conflict:
                t = re.sub("(?i)(^|,\\s*)" + re.escape(_w) + "(?=\\s*(,|$))", "", t)
        return re.sub(",\\s*,+", ",", t).strip(", ")

    parts = [p for p in (_clean(p) for p in parts) if p]
    parts.append(_skin)
    if _is_swim:
        parts.append(_body)
    seen, out = (set(), [])
    for t in ", ".join((p for p in parts if p)).split(","):
        s = t.strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return sanitize_prompt_tags(out, st, theme=theme, framing=framing)


def current_season(today=None):
    """按当天日期判季节：3-5 春 / 6-8 夏 / 9-11 秋 / 12-2 冬"""
    import datetime as _dt

    m = (today or _dt.date.today()).month
    if m in (3, 4, 5):
        return "春"
    if m in (6, 7, 8):
        return "夏"
    if m in (9, 10, 11):
        return "秋"
    return "冬"


def seasonal_guide(theme, workflow=None, today=None):
    """
    四季常装主题 → (季节, {outfit, scene}, 展示用主题名)。
    非该主题、或工作流不在 Anima 两条线时返回 None（其他工作流完全不受影响）。
    """
    t = theme or ""
    if not any((k in t for k in SEASONAL_THEME_KEYWORDS)):
        return None
    if workflow and workflow not in SEASONAL_WORKFLOWS:
        return None
    s = SEASONAL_OVERRIDE if SEASONAL_OVERRIDE in SEASONAL_OUTFIT else current_season(today)
    return (s, SEASONAL_OUTFIT[s], f"{t}·{s}")


ANIMA_FRAMING_TIER = None
FRAMING_POLICY_DEFAULT = (
    ("portrait/close-up", 1 / 3),
    ("upper body", 1 / 3),
    ("cowboy/full body", 1 / 3),
)
FRAMING_POLICY_FULL = (
    ("portrait/close-up", 1 / 3),
    ("upper body", 1 / 3),
    ("cowboy/full body", 1 / 3),
)
FRAMING_FULL_THEME_KEYWORDS = (
    "泳装",
    "泳衣",
    "比基尼",
    "水着",
    "沙滩",
    "海边",
    "度假",
    "礼服",
    "婚纱",
    "舞会",
    "晚礼服",
    "旗袍",
    "长裙",
    "动作",
    "战斗",
    "动态",
    "运动",
    "跑",
    "跳",
    "武",
)


def framing_theme_is_full(theme):
    """该主题是否允许全身（泳装/礼服/动作等）。"""
    return any((k in str(theme or "") for k in FRAMING_FULL_THEME_KEYWORDS))


def choose_framing(theme, workflow=""):
    """三种生产景别等概率；保留主题池接口与强制覆盖优先级。"""
    if FRAMING_OVERRIDE:
        return FRAMING_OVERRIDE
    if ANIMA_PROMPT_V2 and workflow in ("api", "anima_flow"):
        return ""
    t = str(theme or "")
    full = any((k in t for k in FRAMING_FULL_THEME_KEYWORDS))
    pool = FRAMING_POLICY_FULL if full else FRAMING_POLICY_DEFAULT
    import random as _r

    return _r.choices([p[0] for p in pool], weights=[p[1] for p in pool], k=1)[0]


CHAR_SIGNATURE = {
    "hu tao": "black wide-brimmed hat, paper talisman on hat, plum blossom hair ornament, flower-shaped pupils, red eyes, twin tails",
    "furina": "gold crown mini top hat, heterochromia, white hair with blue streaks, droplet ornament",
    "hatsune miku": "aqua hair, very long twin tails, headset, aqua eyes",
    "raiden shogun": "purple hair, long braid, hair ornament, purple eyes, sharp eyebrows, narrow sharp eyes, mature female face, mole under eye, straight bangs",
    "march 7th": "pink hair, blue ribbon, flower hair ornament, heterochromia",
}
OUTFIT_DRIFT_NEGATIVE = "puffer jacket, down jacket, fur collar, fur trim, duffle coat"
ANIMA_EXTRA_TEMPLATE_FIELDS = ("eye_colors", "body", "composition", "depth")
ANIMA_PREFIX = "year 2025, masterpiece, best quality, score_7, safe"
ANIMA_NEGATIVE = "worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, chromatic aberration"
ANIMA_ARTIST_BY_SERIES = {
    "genshin_impact": [
        "@yaner, (@chinikuniku:0.8)",
        "@ciloranko, (@mika pikazo:0.7)",
        "@ciloranko, (@mika pikazo:0.7), (@wlop:0.5)",
    ],
    "honkai:_star_rail": ["@moonya, (@calendulamew:0.8)", "@celtreny, (@jiuchuansi:0.8)"],
    "blue_archive": ["@hwansang, (@doremi (doremi4704):0.8)"],
    "fate_(series)": ["@okonon (kado colda), (@miwa shirow:0.8)", "@neon-tetora, (@wagu neru:0.8)"],
    "vocaloid": ["@makucrp, (@pinocchio-p:0.8)", "@zero (jckz2334), (@kaesmedubu:0.8)"],
    "zenless_zone_zero": ["@hue oo, (@zeroartwo:0.8)", "@beni shake, (@sho yai:0.8)"],
    "wuthering_waves": [
        "@sw haze, (@jvn:0.8)",
        "@dog-san, (@shigureszku:0.8)",
        "@ciloranko, (@mika pikazo:0.7)",
    ],
    "hololive": ["@sui. (suikun), (@advarcher:0.8)", "@saltnvalk, (@nekojira:0.8)"],
    "touhou": ["@uriah-oyu, (@mokoiscat:0.8)", "@ruu (tksymkw), (@moni monico:0.8)"],
    "azur_lane": ["@samip, (@hori (hori no su):0.8)", "@soul (dp11), (@dedorudy:0.8)"],
    "arknights": ["@gou haihaihaihai, (@fan mu zhang:0.8)", "@shirocha tei, (@norizc:0.8)"],
    "idolmaster": ["@eluthel, (@nogreen:0.8)", "@mou (piooooon), (@binsen:0.8)"],
    "umamusume": ["@art (rtrunl), (@moffumoto:0.8)", "@itaba atsushi, (@uwazumi:0.8)"],
}
ANIMA_ARTIST_GENERIC = [
    "@ciloranko, (@mika pikazo:0.7)",
    "@uriah-oyu, (@sw haze:0.8)",
    "@ciloranko, (@mika pikazo:0.7), (@wlop:0.5)",
]
SECONDARY_ARTIST_WEIGHT_MAX = 0.65
ARTIST_GLOBAL_POOL = True


def _all_artist_combos():
    seen, out = (set(), [])
    for combos in ANIMA_ARTIST_BY_SERIES.values():
        for c in combos:
            if c not in seen:
                seen.add(c)
                out.append(c)
    for c in ANIMA_ARTIST_GENERIC:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


ANIMA_ARTIST_ALL = _all_artist_combos()


def _cap_secondary_artist_weights(combo, cap=None):
    """把一行画风串里第 2 位起的 (名字:权重) 截断到 cap；主画风（第 1 位）不动。"""
    cap = float(SECONDARY_ARTIST_WEIGHT_MAX if cap is None else cap)
    parts = [p.strip() for p in str(combo or "").split(",") if p.strip()]
    out = []
    for i, p in enumerate(parts):
        if i > 0:
            m = re.match("^\\((.+):([\\d.]+)\\)$", p)
            if m:
                w = min(float(m.group(2)), cap)
                p = f"({m.group(1)}:{w:g})"
        out.append(p)
    return ", ".join(out)


def _alnum(text):
    return re.sub("[^a-z0-9]", "", (text or "").lower())


def anima_artist_combos(series):
    """
    2026-10-22：默认全局池（解除作品限制）→ 返回 ("global", 全部去重画风组合)。
    ARTIST_GLOBAL_POOL=False 时恢复按作品查表。
    """
    if ARTIST_GLOBAL_POOL:
        return ("global", [_cap_secondary_artist_weights(c) for c in ANIMA_ARTIST_ALL])
    key = _alnum(series)
    if key:
        for tag, combos in ANIMA_ARTIST_BY_SERIES.items():
            if _alnum(tag) == key:
                return (tag, [_cap_secondary_artist_weights(c) for c in combos])
    return (None, [_cap_secondary_artist_weights(c) for c in ANIMA_ARTIST_GENERIC])


SANE_PLACEMENT_NEGATIVE = (
    "objects floating in midair, furniture floating on water, objects standing on the water surface, props on "
    "the sea surface, levitating objects, floating debris, misplaced objects, objects clipping through the "
    "character, props intersecting the body, items embedded in the body, unnatural object placement"
)
CLOTHING_CLARITY_NEGATIVE = "merged clothing, swimsuit fused with stockings, sleeves blended into swimsuit, unclear clothing boundaries, clothing merging into skin"
SANE_PLACEMENT_WORKFLOWS = ("api", "anima_flow")
WORKFLOW_MODEL_INFO = {
    "api": {
        "label": "Anima-2.9B-preview-v1 (int8)",
        "family": "Anima / Cosmos-Predict2-2B 系（danbooru 标签训练）",
        "source": "danbooru + 非动漫艺术图（数百万张）",
        "cutoff": "2026-07",
        "cutoff_year": 2026,
        "cutoff_date": "2026-07",
        "cutoff_precision": "month",
        "danbooru_based": True,
    },
    "anima_flow": {
        "label": "Anima-2.9B-preview-v1 (int8)",
        "family": "Anima / Cosmos-Predict2-2B 系（danbooru 标签训练）",
        "source": "danbooru + 非动漫艺术图（数百万张）",
        "cutoff": "2026-07",
        "cutoff_year": 2026,
        "cutoff_date": "2026-07",
        "cutoff_precision": "month",
        "danbooru_based": True,
    },
    "animagine_xl": {
        "label": "Animagine XL 4.0 Opt (SDXL)",
        "family": "Animagine XL / SDXL（danbooru 标签训练，tag-ordering）",
        "source": "840 万张动漫图（官方卡）",
        "cutoff": "2025-01-07",
        "cutoff_year": 2025,
        "cutoff_date": "2025-01-07",
        "cutoff_precision": "day",
        "danbooru_based": True,
    },
    "nova_xl": {
        "label": "Nova Anime XL ilV190 (Illustrious 系)",
        "family": "Illustrious-XL / SDXL（danbooru 标签训练）",
        "source": "danbooru 动漫图（Illustrious v1.9 血统）",
        "cutoff": "约 2024",
        "cutoff_year": 2024,
        "cutoff_date": "2024",
        "cutoff_precision": "year",
        "danbooru_based": True,
    },
}
CHARACTER_GATE_ATTEMPTS = 3
MAX_WORKFLOW_SWAPS = 2
CHARACTER_GATE_WEB = True
GATE_WEB_MAX_RESULTS = 6
SERIES_MIN_POSTS = 500
EYE_TAG_MODE_WORKFLOWS = ("animagine_xl", "nova_xl")
EYE_VLM_CHECK = False
EYE_VLM_PENALTY = 0.5
EYE_VLM_TIMEOUT = 90
EYE_VLM_MAX_EXTRA = 1
HIRES_FIX = True
HIRES_WORKFLOWS = ()
HIRES_SCALE = 1.5
HIRES_DENOISE = 0.45
HIRES_STEPS = 14
HIRES_CFG = 5.0
ARTIST_TAGS_WORKFLOWS = ("api", "anima_flow")
ARTIST_TAGS_AT_PREFIX = ("api", "anima_flow")
CHAR_POP_OLD_YEAR = 2020
CHAR_POP_OLD_MIN = 500
CHAR_POP_NEW_MIN = 500
CHARACTER_MIN_POSTS = 500
SERIES_DEBUT_YEAR = {
    "gundam": 1979,
    "mario_(series)": 1985,
    "zelda": 1986,
    "final_fantasy": 1987,
    "street_fighter": 1987,
    "dragon_ball": 1984,
    "jojo_no_kimyou_na_bouken": 1987,
    "sailor_moon": 1991,
    "sonic_the_hedgehog": 1991,
    "tekken": 1994,
    "neon_genesis_evangelion": 1995,
    "touhou": 1996,
    "pokemon": 1996,
    "cardcaptor_sakura": 1996,
    "one_piece": 1997,
    "digimon": 1997,
    "naruto": 1999,
    "bleach": 2001,
    "toaru_majutsu_no_index": 2004,
    "fate_(series)": 2004,
    "pretty_cure": 2004,
    "idolmaster": 2005,
    "vocaloid": 2007,
    "league_of_legends": 2009,
    "sword_art_online": 2009,
    "love_live": 2010,
    "date_a_live": 2011,
    "puella_magi_madoka_magica": 2011,
    "infinite_stratos": 2011,
    "houkai_gakuen": 2012,
    "made_in_abyss": 2012,
    "kantai_collection": 2013,
    "kobayashi-san_chi_no_maid_dragon": 2013,
    "granblue_fantasy": 2014,
    "dungeon_meshi": 2014,
    "fate/grand_order": 2015,
    "bang_dream!": 2015,
    "ensemble_stars": 2015,
    "undertale": 2015,
    "re:zero": 2016,
    "kono_subarashii": 2016,
    "kimetsu_no_yaiba": 2016,
    "overwatch": 2016,
    "girls'_frontline": 2016,
    "umamusume": 2016,
    "honkai_impact_3rd": 2016,
    "rurouni_kenshin": 1994,
    "azur_lane": 2017,
    "nier:automata": 2017,
    "hypnosis_mic": 2017,
    "hololive": 2018,
    "nijisanji": 2018,
    "chainsaw_man": 2018,
    "jujutsu_kaisen": 2018,
    "deltarune": 2018,
    "princess_connect": 2018,
    "arknights": 2019,
    "apex_legends": 2019,
    "spy_x_family": 2019,
    "bocchi_the_rock!": 2019,
    "d4dj": 2019,
    "genshin_impact": 2020,
    "project_sekai": 2020,
    "valorant": 2020,
    "oshi_no_ko": 2020,
    "blue_archive": 2021,
    "punishment:gray_raven": 2021,
    "tower_of_fantasy": 2021,
    "nikke": 2022,
    "elden_ring": 2022,
    "lycoris_recoil": 2022,
    "path_to_nowhere": 2022,
    "aether_gazer": 2022,
    "honkai:_star_rail": 2023,
    "reverse:1999": 2023,
    "snowbreak": 2023,
    "girls'_frontline_2": 2023,
    "girls_band_cry": 2023,
    "zenless_zone_zero": 2024,
    "wuthering_waves": 2024,
}


def series_debut_year(series_en):
    """按作品标签查出道年份（归一化后匹配，查不到返回 None）"""
    key = _alnum(series_en)
    if not key:
        return None
    for tag, year in SERIES_DEBUT_YEAR.items():
        if _alnum(tag) == key:
            return year
    return None


SEED_MAX_DEFAULT = 2147483647
SEED_MAX = {
    "api": 2147483647,
    "anima_flow": 2147483647,
    "animagine_xl": 2147483647,
    "nova_xl": 2147483647,
}


def set_active_unet(variant="int8"):
    """
    切换 Anima 权重：**唯一入口**（同时更新 ANIMA_UNET 与 WORKFLOW_SETTINGS，
    因此运行期调用立即生效，不再是导入期快照）。

    variant: "int8"（默认，2.87GB，快）/ "native"（原生 bf16，5.44GB）/ 也可直接传文件名。
    返回实际生效的文件名。
    """
    global ANIMA_UNET
    v = str(variant).lower()
    if v.endswith(".safetensors"):
        fname = variant
    elif v in ("native", "bf16", "fp16", "full"):
        fname = ANIMA_UNET_NATIVE
    else:
        fname = ANIMA_UNET_INT8
    ANIMA_UNET = fname
    for w in ("api", "anima_flow"):
        if w in WORKFLOW_SETTINGS:
            WORKFLOW_SETTINGS[w]["unet"] = fname
    return fname


ARTIST_TAG_PROB = 0.5
ARTIST_CFG_ON = 3.7
ARTIST_CFG_OFF_RANGE = (3.5, 5.0)
FORCE_ARTIST_MAX_YEAR = 2021
FORCE_ARTIST_OVERRIDE = None
NO_ARTIST_MIN_YEAR = 2022
NO_ARTIST_OVERRIDE = None
CHILD_BODY_BANNED_THEMES = (
    "泳装",
    "水着",
    "swimsuit",
    "bikini",
    "比基尼",
    "内衣",
    "lingerie",
    "兔女郎",
    "bunny",
    "湿身",
    "沙滩",
    "泳池",
)


def is_revealing_theme(theme):
    t = str(theme or "").lower()
    return any((str(k).lower() in t for k in CHILD_BODY_BANNED_THEMES))


BANNED_BODY_TAGS = ("child", "loli", "toddler", "kodomo")
BANNED_BODY_RATIO = 0.03
NOVA_FRAMING_POOL = ["upper body", "portrait", "close-up", "bust"]
NOVA_FRAMING_EXTRA = "centered, shallow depth of field"
NOVA_FRAMING_FROM_BELOW_PROB = 0.2
NOVA_FRAMING_NEGATIVE = "full body, full-length, wide shot, legs visible, feet visible, standing legs, distant view, zoomed out, from above"
ANIMAGINE_FRAMING = "(upper body:1.35), centered, shallow depth of field, blurred background"
ANIMAGINE_FRAMING_NEGATIVE = (
    "close-up, extreme close-up, head out of frame, top of head cut off, cut off headwear, cropped head, full "
    "body, full-length, wide shot, legs visible, feet visible, distant view, zoomed out"
)
FRAMING_POOL_WORKFLOWS = ("nova_xl",)
FRAMING_NEGATIVE_WORKFLOWS = ("nova_xl", "animagine_xl")
LIMB_JUDGE = False
LIMB_JUDGE_TARGET = 5
LIMB_JUDGE_MAX_TOKENS = 4500
LIMB_POSE_NEGATIVE = ""
LIMB_POSE_WORKFLOWS = ("api", "anima_flow")
FRAMING_OVERRIDE = None


def _norm_debut_date(value):
    """把 2025-09-15 / 2025-09 / 2025 / 2025年9月15日 归一成 YYYY[-MM[-DD]]；非法返回 None"""
    import re

    s = str(value or "").strip()
    m = re.match("^(\\d{4})(?:[-/.](\\d{1,2}))?(?:[-/.](\\d{1,2}))?$", s)
    if not m:
        m = re.match("^(\\d{4})年(?:(\\d{1,2})月)?(?:(\\d{1,2})日)?$", s)
    if not m:
        return None
    try:
        y = int(m.group(1))
        mo = int(m.group(2)) if m.group(2) else None
        day = int(m.group(3)) if m.group(3) else None
    except Exception:
        return None
    if not 1970 <= y <= 2070:
        return None
    if mo is not None and (not 1 <= mo <= 12):
        mo = None
    if day is not None and (not 1 <= day <= 31):
        day = None
    if mo is None:
        return f"{y:04d}"
    if day is None:
        return f"{y:04d}-{mo:02d}"
    return f"{y:04d}-{mo:02d}-{day:02d}"


def artist_roll():
    """Implementation details: see docs/ARCHITECTURE.md."""
    import random as _r

    if FORCE_ARTIST_OVERRIDE is True:
        return (True, ARTIST_CFG_ON)
    if _r.random() < ARTIST_TAG_PROB:
        return (True, ARTIST_CFG_ON)
    lo, hi = ARTIST_CFG_OFF_RANGE
    return (False, round(_r.uniform(lo, hi), 2))


ANIMA_MODEL_CHOICES = ("int8", "native")


def anima_model_roll():
    import random as _r

    return _r.choice(ANIMA_MODEL_CHOICES)


LLM_CHANNEL_EXTRA_ATTEMPTS = 1
LLM_CHANNEL_RETRY_DELAY_SEC = 60
LLM_CHANNEL_BORROW_ON_FAIL = True
PROMPT_CHANNEL_SHARE_SEEDS = True
CANDIDATE_RUN_RETRIES = 2
GENERATION_CALL_RETRIES = 1


def seed_max_for(workflow):
    """返回当前工作流允许的 seed 上限。"""
    return SEED_MAX.get(workflow, SEED_MAX_DEFAULT)


ANIMA_EXTRA_POSITIVE = ""
KSAMPLER_COMBOS = [
    ("euler", "sgm_uniform", 50, 3.7, "euler + sgm_uniform / 50步"),
    ("res_multistep", "linear_quadratic", 50, 3.7, "res_multistep + linear_quadratic / 50步"),
    ("er_sde", "beta57", 50, 3.7, "er_sde + beta57 / 50步"),
    ("uni_pc", "ddim_uniform", 50, 3.7, "uni_pc + ddim_uniform / 50步"),
]
ANIMA_FLOW_SETTINGS = {
    "cfg_mode": "const",
    "flow_solver": "flow_euler",
    "flow_schedule": "flow_diffusers_linear_shift",
    "flow_shift": 3.0,
}
COMFY_DIR = os.environ.get("COMFY_DIR", "")
COMFY_PYTHON = os.environ.get("COMFY_PYTHON", "")
COMFY_START_ARGS = ["main.py", "--bf16-text-enc", "--listen", "127.0.0.1", "--port", "8188"]
COMFY_BOOT_TIMEOUT = 300
COMFY_AUTOSTART = os.environ.get("COMFY_AUTOSTART", "0") == "1"
FALLBACK_NEGATIVE = "worst quality, low quality, lowres, score_1, score_2, score_3, blurry, jpeg artifacts, bad anatomy, missing fingers, watermark, artist name"
_debut_dates = {}


def char_debut_year(name_en):
    return _debut_dates.get(name_en, {}).get("year")


def char_debut_date(name_en):
    return _debut_dates.get(name_en, {}).get("date", "")


def set_char_debut_year(name_en, year=None, source="", date=None):
    """Remember character-level debut information only in the current process."""
    key = str(name_en or "").strip()
    normalized = _norm_debut_date(date) if date else None
    try:
        parsed_year = int(normalized[:4]) if normalized else int(year)
    except (TypeError, ValueError):
        return None
    if not key or not 1970 <= parsed_year <= 2070:
        return None
    _debut_dates[key] = {"year": parsed_year, "date": normalized or "", "source": source}
    return parsed_year


# Available local illustration themes, including seasonal environments.
LOCAL_THEMES = (
    "泳装",
    "比基尼",
    "和服",
    "浴衣",
    "女仆",
    "圣诞",
    "婚纱",
    "护士",
    "制服",
    "运动",
    "旗袍",
    "礼服",
    "四季常装",
    "春景",
    "夏景",
    "秋景",
    "冬景",
    "背景",
)
