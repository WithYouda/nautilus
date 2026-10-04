# C3 原生思考控制调研

核对日期：2026-10-04。用途：实现前确认厂商原生参数与可借鉴结构。官方文档说明模型规格，不证明任意中转站会完整支持；项目源码只作实现参考，不代替厂商契约。

## 厂商支持情况

| 厂商 / 模型例子 | 原生控制 | 实现注意点与官方依据 |
| --- | --- | --- |
| OpenAI | Responses 用 `reasoning.effort`，Chat 用 `reasoning_effort`。GPT-6 Astra / GPT-6.1 Sol：`low/medium/high/xhigh/max`；GPT-5.6另支持`none`；GPT-5.4：`none/low/medium/high/xhigh`；较早o系列为`low/medium/high` | 不能把所有模型的枚举并集作为每个模型的选项。Astra/6.1 Sol带工具须用Responses，不自动换协议。见[推理指南](https://developers.openai.com/api/docs/guides/reasoning)、[Astra模型页](https://developers.openai.com/api/docs/models/gpt-6-astra)、[当前模型指南](https://developers.openai.com/api/docs/guides/latest-model)、[GPT-5.4](https://developers.openai.com/api/docs/models/gpt-5.4) |
| Anthropic Claude | 支持effort的模型使用`output_config.effort`；较新模型有`low/medium/high/xhigh/max`，4.6没有`xhigh`，4.5只有前三档。自适应思考用`thinking.type=adaptive`；旧模型用`enabled + budget_tokens` | 思考模式、effort、总输出上限是不同参数；有些模型不能关闭，不能把`adaptive`当强度档位。旧预算模式需满足`max_tokens`关系。见[Effort](https://platform.claude.com/docs/en/build-with-claude/effort)、[Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)、[Extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking) |
| Google Gemini | 本项目GenerateContent协议使用`generationConfig.thinkingConfig`。3系列使用`thinkingLevel`：部分模型有`minimal/low/medium/high`，3.8/3.7 Flash和3.1 Pro为后三档；2.5系列使用`thinkingBudget` | `minimal`不等于关闭。2.5 Pro预算128–32768、不能关闭；Flash为0–24576，0关闭、-1动态。level与budget互斥；最新Interactions文档不能直接用于现有GenerateContent适配器。见[GenerateContent思考指南](https://ai.google.dev/gemini-api/docs/generate-content/thinking)、[请求定义](https://ai.google.dev/api/generate-content#ThinkingConfig) |
| xAI Grok | 4.5有`low/medium/high`；4.6/4.7增加`xhigh`，不能关闭；Chat/Responses分别采用`reasoning_effort`/`reasoning.effort` | 多Agent模型同名参数控制Agent数量，不当作同一种思考强度。见[官方Reasoning](https://docs.x.ai/developers/model-capabilities/text/reasoning) |
| DeepSeek | 当前V4实际档位`low/high/max`；Chat用`thinking.type`及`reasoning_effort`，Responses用`reasoning.effort`；默认high，可关闭 | `medium/xhigh`映射到high，`ultra`映射到max，不能展示为额外独立档位。工具续轮需保留原始reasoning_content。见[Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/)、[Chat API](https://api-docs.deepseek.com/api/create-chat-completion/) |
| 阿里云千问 | Qwen3.8常规模型真实档位`low/medium/xhigh`；Omni版本另有完整枚举。较早混合思考模型使用`enable_thinking`开关和`thinking_budget` | 同平台托管其他厂商的控制也可能不同于原厂。Qwen3.8 effort与budget不可同时发送；不把兼容别名误称真实独立档位。见[API参数表](https://help.aliyun.com/en/model-studio/qwen-api-via-dashscope)、[深度思考](https://help.aliyun.com/zh/model-studio/deep-thinking)、[Omni参数](https://help.aliyun.com/zh/model-studio/qwen3-8-omni-flash) |
| Kimi | K3用`reasoning_effort=low/high/max`，默认max且不能关闭；K2.5/K2.6以`thinking.type`开关为主 | 不把Coding Plan参数映射、第三方托管参数与官方通用API混用。见[K3快速开始](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart)、[官方模型选择](https://www.kimi.ai/help/kimi-api/api-model-selection)、[K2.5官方源码说明](https://github.com/MoonshotAI/Kimi-K2.5/blob/master/README.md) |
| Z.ai / GLM | 5.3有`low/high/max`且不能关闭；5.2真正不同的档位为high/max并可关闭。较早系列使用`thinking.type`开关 | 5.2接受的其他字符串会映射为已有档位；5.3普通API与Coding Plan对别名的接受行为不同。见[Deep Thinking](https://docs.z.ai/guides/capabilities/thinking)、[Thinking mode](https://docs.z.ai/guides/capabilities/thinking-mode) |

等级是控制信号，不保证固定思考时长、Token用量或回答质量。省略参数、明确关闭、最低强度必须区分；仅支持预算的模型展示实际预算，不自行包装成厂商的低/中/高。

## 已有实现与取舍

- **RikkaHub**，固定提交`a6dbb8cd2ba8302bd02fb2dbfdb9e06060e7c979`（2026-10-03，AGPL-3.0）：[ChatInput](https://github.com/rikkahub/rikkahub/blob/a6dbb8cd2ba8302bd02fb2dbfdb9e06060e7c979/app/src/main/java/me/rerere/rikkahub/ui/components/ai/ChatInput.kt#L295)、[ReasoningPicker](https://github.com/rikkahub/rikkahub/blob/a6dbb8cd2ba8302bd02fb2dbfdb9e06060e7c979/app/src/main/java/me/rerere/rikkahub/ui/components/ai/ReasoningPicker.kt)、[统一枚举](https://github.com/rikkahub/rikkahub/blob/a6dbb8cd2ba8302bd02fb2dbfdb9e06060e7c979/ai/src/main/java/me/rerere/ai/core/Reasoning.kt)。借鉴输入区附近的快捷入口。其统一枚举和固定Token换算、Gemini OFF降成minimal、所有Claude走adaptive不照搬；Nautilus按作者要求放在输入区右侧，并按真实规格过滤。
- **Vercel AI SDK**，固定提交`15f1a4d0531ac641a4a4d9cc602c0536c1906834`（2026-10-03，Apache-2.0）：借鉴原生参数优先、能力与选择分离、每次工具续轮使用同一配置；见[OpenAI能力表](https://github.com/vercel/ai/blob/15f1a4d0531ac641a4a4d9cc602c0536c1906834/packages/openai/src/openai-language-model-capabilities.ts)、[Anthropic适配](https://github.com/vercel/ai/blob/15f1a4d0531ac641a4a4d9cc602c0536c1906834/packages/anthropic/src/anthropic-language-model.ts#L594)、[工具轮配置](https://github.com/vercel/ai/blob/15f1a4d0531ac641a4a4d9cc602c0536c1906834/packages/ai/src/generate-text/generate-text.ts#L973)。不采用“不支持便warning后删除”的行为，不复制跨厂商强度合并或百分比预算映射。Gemini应防止合并出level与budget同时存在的请求。

本项目保留已有Python四协议适配器、工具循环和冻结快照，不引入整个SDK，不复制上述项目代码。源码调研已发现版本漂移：例如AI SDK的DeepSeek兼容映射与当前原厂xhigh映射不同，因此官方文档和实际接口约束优先。

## 本项目落实边界

1. 入口：作者已确认输入框附近、优先右侧；快选持续用于当前对话，可选择仅本次及恢复继承，生成中修改只影响下一次发送。
2. 配置：沿用五级模型控制、旧页面冲突校验和已有运行快照；显式模型切换后重新检查强度是否兼容，不静默换模型或降档。
3. 能力：按有出处的具体模型/协议规格登记；自定义别名、中转差异提供显式配置入口，未知保留未知，不从返回的思考文字反推支持等级。
4. 传输：原生参数进入实际HTTP正文，覆盖两处学习对话、普通请求和工具续轮；不靠系统提示模拟参数，不改工具或资料权限。模型是否实际遵循与参数是否已传递分开验证。
5. 验证：捕获实际出站请求字段，检查默认/关闭/不同档位、协议差异、模型切换、历史冻结、仅本次、重试及两处输入区交互；真实模型检查仅用合成内容。
6. 模型策略预设形式尚在等待作者对已提出具体方案的答复；不将研究建议或示例名称视为已确认策略。
