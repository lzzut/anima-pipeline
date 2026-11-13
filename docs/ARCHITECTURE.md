# 提示词链、代码入口与微调边界

本文描述当前默认基线：DeepSeek V4 Flash 1017（请求名 `deepseek-flash`）+ Anima-2.9B-preview-v1，单人物、`stable` 提示词通道，两条本地 ComfyUI 采样工作流。改变模型、节点或设计开关后，应重新验证实际提示词与图片，不能沿用原配置的效果推断。

画面效果的实图与字段对应见 [`SAMPLES.md`](SAMPLES.md)：时段／天气、动作／镜头、换装／光照及同提示词换 seed 均有真实图示。实际正负提示词与绘图参数保存在 [`sample_prompts.json`](sample_prompts.json)，仅作为文档数据，不参与运行。实图只能佐证可见结果；事实引文支持、修正上限和预算恢复须查看代码及本次运行记录。

## 包目录与导入

实现位于 `anima_pipeline/` 包：`cli/` 负责入口与流程串接，`characters/` 负责人物事实及选材，`prompting/` 负责设计、写作和审查，`research/` 负责联网与标签数据，`rendering/` 负责 ComfyUI、评分和画廊。配置在 [`anima_pipeline/config.py`](../anima_pipeline/config.py)，两条模板在 [`workflows/`](../workflows/)。各模块保留原函数和设计职责，以完整包名导入，包括函数内部的延迟导入。

根目录 `custom_entry.py`、`pipeline_character.py` 仅转交包内实现，继续支持原 CLI 命令。统一入口为 `python -m anima_pipeline custom` 和 `python -m anima_pipeline auto`；代码调用使用 `from anima_pipeline.cli.custom_entry import generate` 或 `from anima_pipeline.cli.pipeline_character import run_auto`，配置使用 `from anima_pipeline import config`。不要将各子目录单独加入 `sys.path`，否则可能加载两份配置，导致临时参数覆盖和恢复不一致。

[`anima_pipeline/paths.py`](../anima_pipeline/paths.py) 从自身位置确定项目根；`.env`、静态标签库、工作流模板、默认输出和 ComfyUI 启动日志均以该根目录定位。包内源码目录不存放运行数据。从其他工作目录启动时，传入根目录兼容脚本的绝对路径即可。

后文表格中省略前缀的模块名，均指上述子包中的同名文件；完整源码链接见 [README 微调入口](../README.md#输出与微调入口)。

## 入口与数据生命周期

`anima_pipeline.cli.custom_entry.generate` 创建任务输出目录，将手动人物交给 `anima_pipeline.cli.pipeline_character._prepare_character_facts`，再把**同一个 Session**传入 `_build_all_channel_prompts`。自动入口 `run_auto` 先通过 `select_auto_character` 选角／门控和事实预检，再调用同一个 `anima_pipeline.cli.custom_entry.generate`，不会再抽取一次已批准事实。

自动选角按角色和作品标准标签、角色级登场日期及来源作范围判断。投稿数量是模型熟悉程度的启发式，不能证明某个角色实际进入过训练集；联网角色级证据路径与离线热度路径的条件不同，不能把“所有通过人物都统一满足某个投稿阈值”作为契约。

每次任务的资料、审查、阶段输入输出存于它自己的 `数据/`；新任务不加载旧资料、性格卡、场景历史或拒绝名单。Session 内通过 `_prepared_fact_card`、`_selected_variant` 和 `_persona_results` 复用同一任务的结果，保留质量功能并限制重复调用。`save_card` 只保存内存副本，`prepare_card` 的 `how="session"` 表示本次会话复用。

## 按执行顺序阅读代码

| 阶段 | 主要位置 | 输入、输出与约束 |
|---|---|---|
| 实际研究 | `anima_pipeline.prompting.prompt_refinement.read_character_references`、`web_search.search/fetch_page` | 人物／作品／版本 → 正文、URL、时间及来源等级。摘要不能假装是正文；补搜有数量边界。 |
| 来源和版本 | `anima_source_policy` | 人物选材上限与描述更新时间分开；优先有权威性的较新来源，保留版本排除规则，不以未知时间伪造发布日期。 |
| 事实抽取 | `Session.fact_card`、`validate_card` | 带逐字引文的事实列表，标明 hair/eyes/face/accessory/body/default_outfit、可见部位和版本。引文归属、类型与术语均核对。 |
| 事实批准／修正 | `anima_character_card.prepare_card/approve_with_repairs` | 每条事实必须有明确支持状态；修正仅处理未支持事实并重新核对，不能删除难题来伪装通过。 |
| 小幅外观分歧 | `anima_character_variants` | 有证据的小颜色／饰品差异可分成最多 3 张完整候选卡；一次任务只抽一次。禁止借此改变物种、年龄、体型、主要轮廓或混入排除版本。 |
| 性格提取 | `Session.persona_traits` | 从已批准卡的来源正文提取长期性格，逐字核对；只影响动作／表情设计。缺省可用，不造人格；同 Session 复用，不写长期文件。 |
| 主题简报 | `theme_brief`、`Session._brief` | 区分创意换装与保留原装，协调本次季节、室内外、时段、天气和场景来源。 |
| 服装设计 | `Session.plan_art_direction` 中 `design_outfit` | 给定人物事实和主题，确定配色、剪裁、材料、层次与饰品；不创造人物身份。 |
| 场景／动作 | 同函数中 `design_scene` | 一个画面、一个物理时刻；动作有合理支撑和简单接触，避免复杂人体器械操作。 |
| 构图协调 | 同函数中 `resolve_composition` | 把动作与相机描述分开，确定画面焦点、裁切、前后关系、需保留动作和应省略次要细节。 |
| 结构化写作 | `Session.write` | 选取可见身份事实，填画面状态和负面词；已设计的主稿字段由程序插入，写作不能另起一稿覆盖它们。 |
| 环境设计 | `Session.design_environment` | 在既定人物／衣服／动作／相机下补足背景与光照，协调近中远景、主光、材料和反射；只改获准字段。 |
| 最终文字协调 | `anima_pipeline.prompting.anima_visual_focus.refine` | 仅 `pose/expression/composition` 可改；服装、环境、光照、支持接触和身份不可擅自改写。动作与镜头字段不再重复抢占职责。 |
| 本地检查及语义审查 | `validate_draft`、`anima_prompt_contracts`、`Session.review` | 可见性、事实引用、主题、场景关系、光照、脚部服装、术语与否定冲突。本地能确定的规则不交给 LLM 猜。 |
| 局部修正与复核 | `Session.repair`、`Session.build` | 必须归因到被审查的真实文字／字段；只修已报告字段和直接必要依赖。保留有效服装、场景、相机及动作意图。 |
| 编译／冻结 | `compile_draft`、`finalize_render` | 质量前缀 + 单人标签 + 人物作品 + 已批准可见身份／体型 + 创意字段；冻结正文和 hash，不静默截断。 |
| 本地采样／排序 | `comfy_runner.generate_images/_run_once/_score_image` | 同提示词换 seed，保存实际图和候选数据，本地美学选图。 |

## 关键数据契约

事实卡以 `character_key` 绑定人物、作品、外观版本、选材上限和 schema。事实带 `id`、`attribute`、`value_en`、`source_id`、`quote`、`version_scope` 等。`gray-purple` 之类颜色词需要绑定属性，`gray-purple eyes` 才能作为瞳色事实。饰品必须知道附着于头发、身份配饰还是官方服装；换装时不让原装肩饰、披肩、长手套从“身份”字段绕回去。

`scene_state` 包含视角、姿态、支撑、身体接触、`visible_parts` 和遮挡原因。`pose` 陈述身体动作与物体关系，`composition` 陈述相机、裁切和人物位置；地面支撑可以在画面外存在，但不能因此要求被裁掉的脚出现在图里。`identity_fact_ids` 只能选择已有事实，所有可见且关键的身份事实都必须保留；确实不可见才能给出物理遮挡理由。

保真规则位于 `anima_pipeline/characters/anima_fact_semantics.py`：不能仅凭引文逐字存在就把相近词、不同数量或不同附着部位混成同一事实。语义审查也要判断上下文及归属。例如一个具体花形不能因为近义联想被自动换成另一种花；不确定就保留原术语或标为未支持。

写作稿的渲染字段为 `outfit/expression/pose/scene/lighting/composition/negative`，并附身份 ID、画面状态等契约。场景和光照只能描述同一个地方、同一时间；候选改变视角或裁切时，服装可见性、表情及依赖字段须一起一致，不能仅改一句镜头词。

默认写作仍要求 `stable` 备用姿势对象，但 `ANIMA_SAME_PROMPT_SEEDS=True` 将实际渲染固定在主稿，未渲染替代稿的语义问题不应阻塞主稿。不要误以为五个候选各运行了一次完整提示词链。

## 修正、预算与停止条件

- 事实修正 `MAX_FACT_REPAIR_ROUNDS=2`；修正后完整复核。证据不足和两轮修正耗尽可触发自动换人，`MAX_CHARACTER_REPLACEMENTS=2`，共最多 3 人。重复失败人物不在同任务内重新研究。
- 自动入口门控最多 9 次尝试。密钥、传输、无效审查返回或全局预算异常直接显式失败，不无休止选新人物。
- 默认设计／环境／视觉协调开启时，画面修正最多 3 轮；关闭这些阶段时可能按代码分支收紧为 2 轮。超过上限不渲染未通过的稿。
- 输出预算不是重试次数。设计、稳定写作、画面修正 32k；事实及语义审查 48k。`persona` 等未单独登记角色使用 Session 的较小默认值 16k。
- API 明确 `max_output_tokens` 耗尽才升至 64k，事实范围一次，后续所有文字阶段共一次。用同一个 Session 从预检走到出图，不重建会话绕过恢复次数。
- `request_limit` 从基础额度、启用设计阶段及一次性 allowance 计算，预留耗尽恢复槽位；逻辑请求和物理请求同时受限。当前默认单 `stable`、人物预检＋性格提取均启用且正常走到 build 时通常为 22 个请求槽位，这是上限，不是保证每次发 22 次请求。以审计记录为准。

`anima_pipeline.cli.pipeline_character._create_response` 对新链关闭 SDK 隐式重试；`Session.request` 传 `max_attempts=1`。`require_completed_response` 检查真实状态，不能把因预算耗尽被截断的 JSON 当成成功。

选角的联网工具循环保留响应中的 reasoning 内容和工具 `call_id`，再附真实本地搜索执行结果。只回填函数结果、丢掉 thinking 内容，会使服务拒绝后续请求。事实链的搜索由研究模块承担，设计／写作／审查调用不再任意联网。

审查材料采用引用上下文窗口和来源偏移／hash，避免把全部冗长正文塞入每轮。引文仍需在真实被审查文本中逐字对应；归因修复只纠正定位，不能偷偷换掉原本的审查结论。

## 实际渲染与评分

`finalize_render` 记录可复核的正负提示词对；`anima_pipeline.rendering.comfy_runner.format_prompt` 的 V2 路径保留正文，并按允许规则注入画风标签。`_build_workflow` 根据 `_meta.title` 填 `positive_prompt/negative_prompt/ksampler/anima_sampler`；修改 JSON 时这些标题与输入关系必须一起保持。

`generate_images` 在一组候选内固定一次权重、采样器、CFG 和画风，只改变 seed。`_run_once` 将实际提交图及文本 hash 写到当前任务，候选记录写实际正负提示词。所有候选都留存，最高分复制到本地“程序选中图”。

美学模型为 [`kawaimasa/kawai-aesthetic-scorer-convnextv2`](https://huggingface.co/kawaimasa/kawai-aesthetic-scorer-convnextv2)，等级期望分为 `5*p(SS)+4*p(S)+3*p(A)+2*p(B)+p(C)`。当前默认不做身份审图、眼部 VLM 惩罚或启用顶部像素罚分。评分缺失会得到 0 分并退化为同分随机选择，不应把这个结果当作模型偏好。

基础依赖包含 Pillow；不要通过移除它来运行评分：旧兼容分支在完全缺少 Pillow 时可能给随机值，不能用于验收。评分环境应按 README 预先下载并单独确认。

## 微调地图

| 目标 | 设置／函数 | 调整边界 |
|---|---|---|
| 换 API 或 LLM | `DEEPSEEK_MODEL/BASE_URL`、`_call_responses/_to_input_item` | 不只是改名称；确认 Responses、thinking 回填、工具契约、上下文和输出限额。 |
| 换绘图模型 | `WORKFLOW_SETTINGS`、模板、`compile_draft`、画风策略 | 重新验证标签语法、身份知识、编码器、负面词、CFG、分辨率；当前编译器只适配 Anima。 |
| 人物范围 | `WORKFLOW_MODEL_INFO`、`anima_pipeline.characters.character_gate.accepts` | 不以作品发行年代替人物登场年，不用旧缓存掩盖新证据问题。 |
| 衣服细节 | `outfit_design_instructions`、`writing_card` | 从设计层改款式／材料，保持身份和原装分离；不要在多个层重复覆盖衣服。 |
| 背景和光照 | `environment_direction`、`environment_direction_instructions`、主题场景配置 | 保持镜头、空间、时段一致；别用增加形容词或曝光来代替空间设计。 |
| 动作／相机 | `action_camera_instructions`、`resolve_composition`、`anima_visual_focus` | 先排字段冲突，调整裁切时同步可见性；保持单一物理时刻。 |
| 性格与动作 | `ANIMA_PERSONA_TRAITS`、`persona_traits`、`daily_action` | 只用有据长期特征；一时表情不当作人格。 |
| 场景多样性 | `THEME_SCENE_VARIANTS`、`SCENE_CONTENT_SOURCE`、时段／天气池 | fixed/mixed/deepseek 是场景来源，不是绘图工作流。 |
| 画风与 CFG | `ANIMA_ARTIST_*`、`ARTIST_*`、`anima_artist_combos` | 内部名称历史保留；菜单叫画风。副标签实际权重会封顶 0.65。 |
| 实际构图比例 | `workflows/workflow_*.json` 的 latent 节点 | 修改图像尺寸后验证主体比例、衣服可见范围和背景，而非强行补回画面外的部位。 |
| 修正预算 | `ANIMA_*_MAX_OUTPUT_TOKENS`、`Session.request` | 初始预算须低于恢复预算，恢复上限不大于 64k；别把每个阶段单独恢复改成无限循环。 |
| 同提示词选 seed | `ANIMA_SAME_PROMPT_SEEDS`、`generate_images` | 默认 True；切为多稿模式后重新验证候选间依赖，不要直接拿原有成功率比较。 |

`ANIMA_CAMERA_DIRECTION=False`：当前使用构图协调层，默认没有再加一个独立 camera 写作调用。`ANIMA_SECOND_REVIEW_MODEL=""`：没有默认多审稿模型。`ANIMA_PROMPT_MAX_CHARS=16000` 是异常长度拒绝上限，不是目标字数，也不是绘图编码器的准确 token 上限；可选 `ANIMA_TOKENIZER_ROOT` 诊断不能代替实际节点行为。

仓库保留的 `anima_pipeline/prompting/anima_prompt_experiments.py` 是被编译／写作层导入的策略配置模块，默认 `baseline`；它不是会自动启动测试的入口。未注册的旧模型兼容分支不等于公开支持那些模型，正式入口只提供 `api/anima_flow`。公开包不包含内部测试脚本或原始测试目录，经过筛选和脱敏的静态样图仅用于文档展示。
