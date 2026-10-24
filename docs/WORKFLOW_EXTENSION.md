# 添加自定义工作流（API / KSampler）

公开版允许把符合约定节点结构的 ComfyUI **API 格式工作流**加入 `WORKFLOW_POOL`。  
这里说的“可用”，不是把 JSON 丢进目录就自动扫描；还需要在 `config.py` 注册三项：工作流设置、模型档案、工作流池。

---

## 1. 节点契约

复制 `workflow_api.json` 作为模板，保留这些 **`_meta.title`**：

| `_meta.title` | 作用 |
|---|---|
| `positive_prompt` | 正向提示词节点 |
| `negative_prompt` | 负向提示词节点 |
| `ksampler` | 采样节点，需有 `seed` / `steps` / `cfg` / `sampler_name` / `scheduler` |
| `anima_sampler` | 仅 AnimaFlow 线路使用，普通工作流不要用 |

加载器使用 `UNETLoader` 或 `CheckpointLoaderSimple`，保存节点使用 `SaveImage`。  
如果 `ksampler` 节点没有 `_meta.title = "ksampler"`，代码不会更新它的 seed/步数/CFG。

---

## 2. 注册到 config.py

假设新文件叫 `workflow_my_model.json`：

```python
WORKFLOW_MY_MODEL_PATH = os.path.join(BASE, "workflow_my_model.json")

WORKFLOW_SETTINGS["my_model"] = {
    "path": WORKFLOW_MY_MODEL_PATH,
    "unet": "my_model.safetensors",   # 或 "ckpt": "my_model.ckpt"
    "steps": 30,
    "cfg": 5.0,
    "sampler": "euler",
    "scheduler": "normal",
    "prompt_profile": "generic",
}

WORKFLOW_POOL.append("my_model")
```

`WORKFLOW_SETTINGS` 里的 `sampler` / `scheduler` 必须写明；否则 `None` 会覆盖工作流 JSON 里的原值。

---

## 3. 注册模型档案（门控需要）

`character_gate.accepts()` 会用 `WORKFLOW_MODEL_INFO[workflow]` 判断角色是否在模型知识范围内。缺少这个 key 会直接判未知工作流。

```python
WORKFLOW_MODEL_INFO["my_model"] = {
    "label": "My Model",
    "family": "MyModel / SDXL",
    "source": "danbooru 训练",
    "cutoff": "2025-01",
    "cutoff_year": 2025,
    "cutoff_date": "2025-01",
    "cutoff_precision": "month",
    "danbooru_based": True,
}
```

如果新模型不是 Danbooru 标签系，或你不想让它走角色年限门控，需要自己调整 `WORKFLOW_MODEL_INFO` 和门控逻辑；不要在未验证的情况下把 `danbooru_based` 设为 `True`。

---

## 4. 提示词适用范围（重要）

**Anima-2.9B 的提示词结构不是通用格式。**

当前 Anima 线路默认使用：

```text
year 2025, masterpiece, best quality, score_7, safe,
1girl, solo, <character>, <series>,
<artist combo>, <outfit>, <pose>, <expression>,
<scene>, <lighting>, <detail tags>
```

这套结构、质量词、画师串、负面词以及 50 步参数，都是围绕 Anima-2.9B / 对应文本编码器调过的。

添加自己的模型时要注意：

- 不同模型的文本编码器可接受长度不同（77 / 512 / 更长），长 Danbooru 串可能被截断。
- 不同 VAE、CLIP、模型家族的提示词语法不同；Anima 的 `score_7`、画师 `@` 串、质量前缀不一定适用。
- 某些模型需要自然语言 caption，而不是逗号标签串。
- 某些模型不适合 Anima 的默认负面词或 50 步；步数、CFG、sampler 应按新模型自己的模型卡设置。
- 自定义工作流默认 `prompt_profile: "generic"`，不会自动套 Anima 前缀；但本地拼装流程仍会保留通用负面和主题处理。真正要适配新模型，应修改 `format_prompt()` 或为它单独写提示词生成逻辑。

**不要假设“能出图”就等于“提示词适配”。** 添加模型后应先用固定 seed 做小样本验证，再放进自动主链。

---

## 5. 其他限制

- 自定义工作流默认不参与画师串、Anima 权重随机、眼部补强、hires fix；需要时显式配置 `artist_tags` 或改代码。
- 如果工作流里有 `CLIPSetLastLayer`，当前代码仍会写 Anima 默认的 `-2`；非 Anima 模型如果需要别的 CLIP skip，请删除该节点或改 `_build_workflow`。
- `custom_entry.py` 的模型菜单目前只列系统模型；加了工作流但想在手工入口里选，需要同步改 `SYSTEM_MODELS`。
- 公开版不包含模型权重、VAE、CLIP；这些仍需在 ComfyUI 侧准备。

---

## 6. 验证

本次验证使用一个临时 KSampler 工作流，确认：

- `choose_workflow()` 能从 `WORKFLOW_POOL` 选中自定义 key
- `_build_workflow()` 会替换正向/负向、seed、steps、cfg、sampler、scheduler、UNET 名
- 自定义 `prompt_profile: "generic"` 不会加 `year 2025` 前缀

如果自定义工作流的采样参数没有变化，第一检查 `_meta.title` 是否为 `ksampler`。
