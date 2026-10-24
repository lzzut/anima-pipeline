# custom_entry.py 使用说明

`custom_entry.py` 是手工入口：你先选已注册工作流，再指定角色、采样器和画师组合，跳过自动选角与角色门控。

适合：

- 已经知道要画哪个角色，想换工作流、采样器或画师组合
- 想固定 seed 复现某张图
- 想先确认 ComfyUI / 提示词链路是否正常
- 不想让自动选角改变角色

不适合：

- 不知道画谁，想让 DeepSeek 自动选角 → 用 `pipeline_character.py`
- 需要角色能力门控、热度过滤、自动换人 → 用主链

---

## 三条命令

| 命令 | 作用 | 需要 DeepSeek key | 需要 ComfyUI | 出图 |
|---|---|---|---|---|
| `python custom_entry.py --list` | 列出已注册工作流、采样器、画师组合 | 否 | 否 | 否 |
| `python custom_entry.py --dry-run` | 完整走一遍菜单，只打印结果 | 否 | 否 | 否 |
| `python custom_entry.py` | 真正生成一张图 | 是 | 是 | 是 |

推荐顺序：

```powershell
python custom_entry.py --list
python custom_entry.py --dry-run
python custom_entry.py
```

---

## 1. 查看选项

```powershell
python custom_entry.py --list
```

输出包括：

- 所有已注册工作流；默认是 `api`、`anima_flow` 两条 Anima 线
- 每个工作流对应的采样器组合：`api` 默认 4 组，`anima_flow` 固定 1 组，自定义工作流看 `sampler_combos`
- 27 组去重后的画师组合

自定义 workflow 不能只放 JSON；必须先在 `config.py` 注册，详见 [WORKFLOW_EXTENSION.md](WORKFLOW_EXTENSION.md)。

这一步不会调用 DeepSeek，也不会连接 ComfyUI。

---

## 2. 演练输入

```powershell
python custom_entry.py --dry-run
```

它会依次询问下面的问题，最后打印：

```text
[生成] Anima-2.9B api | 初音未来 | 主题 四季常装 | 景别 cowboy shot
       画师：无 | 采样器：作者最爱：euler + sgm-uniform / 50步 / cfg3.7
[dry-run] 不实际出图
```

`--dry-run` 不会：

- 调用 DeepSeek
- 启动或连接 ComfyUI
- 写图片
- 写 `last_entry.json`

但仍然要把所有输入走完。

---

## 3. 实际出图

### 前置条件

```powershell
$env:DEEPSEEK_API_KEY = "你的 key"
```

ComfyUI 需要已经运行，或者配置自动拉起：

```powershell
$env:COMFY_DIR = "C:\path\to\ComfyUI"
$env:COMFY_PYTHON = "C:\path\to\ComfyUI\venv\Scripts\python.exe"
```

### 启动

```powershell
python custom_entry.py
```

### 完整交互示例

下面以“初音未来 / Vocaloid / 不加画师 / 默认采样器”为例：

```text
选择工作流编号：1
  1 = Anima-2.9B-preview-v1 [api]
  2 = Anima-2.9B-preview-v1 [anima_flow]
  N = config.py 里注册的自定义工作流（如果有）
  9 = 修改 ComfyUI 路径
  q = 退出

选择采样器组合编号（默认 1）：1
  api：4 组 Anima KSampler 组合
  anima_flow：固定 Flow 采样器，自动使用
  自定义：有 sampler_combos 才显示多组；只有一组时自动使用

选择画师组合编号（0=不加画师，默认 0）：0
  0 = 不注入画师串
  1~27 = 对应画师组合

人物中文名：初音未来
作品中文名：Vocaloid
人物英文标签（如 furina_(genshin_impact)）：hatsune_miku
作品英文标签（如 genshin_impact）：vocaloid
主题（默认 四季常装）：四季常装
景别（默认 cowboy shot）：cowboy shot
seed（默认 20261022）：20261024
```

### 输入字段说明

| 输入 | 说明 | 示例 |
|---|---|---|
| 人物中文名 | 只用于日志/文件名，不进入英文提示词 | `初音未来` |
| 作品中文名 | 只用于日志/文件名 | `Vocaloid` |
| 人物英文标签 | 必须是 Danbooru 角色标签 | `hatsune_miku` |
| 作品英文标签 | Danbooru 作品/版权标签 | `vocaloid` |
| 主题 | 决定服装/场景关键词 | `四季常装`、`泳装`、`和服` |
| 景别 | `cowboy shot` 七分身；`full body` 全身 | `cowboy shot` |
| seed | 固定后便于复现 | `20261024` |

带歧义的角色用 `角色_(作品)` 写法：

```text
furina_(genshin_impact)
march_7th_(honkai:_star_rail)
```

### 菜单里的特殊选项

- `9`：修改 ComfyUI 目录/Python 路径，保存到 `user_settings.json`，然后回到工作流选择
- `q`：退出
- 画师组合填 `0`：不注入任何画师串

---

## 输出

成功后会生成一张图和一个记录文件：

```text
output/_custom_entry/<YYYY-MM-DD>/<角色>_<主题>.png
output/_custom_entry/<YYYY-MM-DD>/last_entry.json
```

`last_entry.json` 记录本次 workflow、模型、角色、画师、采样器、文件路径和美学分。

---

## 和主链的区别

| | `custom_entry.py` | `pipeline_character.py` |
|---|---|---|
| 选角 | 你手动指定 | DeepSeek 自动选角 |
| 角色门控 | 无 | 有 |
| 生成张数 | 1 张 | 多张候选后选优 |
| 适合 | 已知角色、固定 seed、换采样器/画师 | 自动日更、探索角色 |

因为不经过门控，模型不认识的角色也可能出“通用脸”。这是手工入口的预期行为。

---

## 常见问题

**`--list` 需要 key 吗？**  
不需要。它只读取 config 里的组合列表。

**`--dry-run` 为什么还要输入？**  
它要验证菜单和参数收集流程，只是不调用 API、不出图。

**报 401 / 鉴权失败？**  
检查 `DEEPSEEK_API_KEY` 是否设置，以及是否有可用额度。

**报 ComfyUI 连接失败？**  
先运行：

```powershell
python ensure_comfyui.py --status
```

**`anima_flow` 报未知节点？**  
安装提供 `AnimaFlowCorrectiveSampler` 的 ComfyUI 扩展，或改选模型 `1`（api 线路）。

**中文名能直接当角色标签吗？**  
不能。英文标签必须使用 Danbooru 标签；中文名只用于日志和文件名。
