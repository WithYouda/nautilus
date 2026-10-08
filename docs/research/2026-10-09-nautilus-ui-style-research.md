# 学海无涯首套界面风格调研

调研日期：2026-10-09（Asia/Shanghai）。状态：研究建议，尚未由作者选定或批准实施。

## 结论先行

推荐首套采用**内容优先的现代扁平化，保留适度层次与明确的操作提示（Flat 2.0 / almost flat）**。以 Material 3 的组件状态、视觉层级和移动交互规则作为主要设计基线，以 Todoist 的日常安排、Notion 的内容组织、NotebookLM 的学习工作区为具体参照。不是直接套默认紫色、指定组件库或复制某个产品。

这是基于学海无涯中文长文、公式、代码、计划与来源回看的适配判断。没有可靠证据可以把某一风格宣称为“全球最多人喜欢”。上一轮“清爽现代 / 纸感阅读 / 柔和亲切”没有充分研究支撑，不继续作为既定候选集。

作者已明确：多套风格是否改变页面排布，留到设计多套风格时讨论。本报告只建议第一套，不预先限制未来风格、排布或个性化能力。

## 1. 调研方法与证据边界

覆盖五套成熟设计体系：Google Material、Apple HIG / Liquid Glass、Microsoft Fluent 2、Ant Design、IBM Carbon；七个相关产品：Notion、Todoist、Obsidian、Goodnotes、Duolingo、NotebookLM、Linear。补查腾讯 ima 和飞书作为中文产品线索。对照 NN/g 的点击辨识研究和 W3C 可访问性要求。

证据分三类：

- **官方事实**：原始发布、产品帮助、设计团队说明、研究方法与采用规模。注明时间和统计口径。
- **视觉观察**：公开的应用内界面示例；本次主Agent实际截取并看过 Todoist 中文桌面/手机合成图、Linear 2026 导航改版、NotebookLM 三栏示例、Goodnotes 文字文档/数学界面、Google Expressive 研究示例。它们是官方展示材料，不是登录后独立操作验收。
- **项目判断**：这些做法如何适用于学海无涯。明确为建议，不升级为已确认产品决定。

没有进行代表性用户调查或跨产品可用性实验。用户数、月活、下载量、平台安装量不能互换；更不能据此证明用户因某种颜色或圆角选择了产品。未把设计社区点赞、营销首页、官网自称“第一”用作审美排名。

历史界面有借鉴价值，但不冒充当前安装版本。尤其 Obsidian 1.0 和 Duolingo 路径改版材料来自 2022 年；NotebookLM 三栏说明来自 2024 年。当前公开来源核对截至调研日。

## 2. “风格”和“设计体系”需要分开

扁平化、拟物、玻璃质感描述视觉表达；Material、Fluent、HIG 是包括布局、状态、交互与可访问性的体系；卡片/网格是组织方式；深色是显示模式。这些不是同一级、互斥的选项。

因此，不能把“玻璃、卡片、深色、Material”排成一个所谓流行度榜单。一个成熟产品可以在平实正文上使用少量有层次的浮层，也可以在不同场景使用不同密度。

| 设计体系 | 核实内容与一手来源 | 对学海无涯的借鉴判断 |
| --- | --- | --- |
| Material 3 / Expressive | Google公开了体系与研究；文字分正文、标题、标签等角色，长文强调可读性。[字体规则](https://m3.material.io/styles/typography/applying-type)、[色彩角色](https://m3.material.io/styles/color/the-color-system) | 适合作为主要组件与移动交互基线。重要动作可以鲜明，正文保持稳定；不必照搬大字号、强色块或默认配色 |
| Apple HIG / Liquid Glass | Apple明确区分内容与导航/控件层，并反对内容列表玻璃化、玻璃叠玻璃。[WWDC25原始讲解](https://developer.apple.com/videos/play/wwdc2025/219/) | 是主流平台方向，不能简单说不稳或过时；但完整光学/自适应效果不宜成为跨平台Web首套的必要条件 |
| Fluent 2 | 强调熟悉的平台操作、专注与减少噪声；有多平台组件及可访问性指导。[原则](https://fluent2.microsoft.design/design-principles)、[布局](https://fluent2.microsoft.design/layout)、[实际Teams改版](https://microsoft.design/articles/designing-the-new-era-of-teams/) | 适合校对桌面工具、层级与复杂状态；不把整个学习界面做成企业办公控制台 |
| Ant Design | 以企业产品为主要背景，具有明确的字体、表单与状态规则。[介绍](https://ant.design/docs/spec/introduce-cn/)、[字体](https://ant.design/docs/spec/font/) | 中文设置页和密集控件可参考；其14px正文基准不直接照搬为手机长篇学习文字 |
| IBM Carbon | 面向IBM产品生态，提供一致、模块化、可访问的组件及复杂数据组织。[官方介绍](https://www.carbondesignsystem.com/getting-started/about-carbon)、[网格](https://www.carbondesignsystem.com/building-blocks/foundations/2x-grid/overview) | 适合核对图表和信息结构；企业软件的密度与品牌表达，不作为个人学习首页的整体样板 |

这五套体系的成熟度不能换算成用户审美满意度。本次推荐Material作主基线是项目取舍，并非证明它在所有平台优于其他体系。

## 3. 广泛采用的证据：数字说明到哪里

| 产品 | 官方数据及时间 | 不能据此推导什么 |
| --- | --- | --- |
| Notion | 2024-09-03文章宣布前一个月超过1亿用户。[原文](https://www.notion.com/blog/100-million-of-you) | 不是1亿月活，也不是对2026界面风格的投票 |
| Todoist | 调研日官网自报50M+ professionals；未说明活跃周期及原始统计日。[官网](https://www.todoist.com/) | 不记为5000万MAU，不采纳其“第一”的营销排名 |
| Goodnotes | 2025-09-23新闻稿报告2500万以上月活。[原文](https://www.goodnotes.com/press/first-bridge-digital-ink-generative-ai-productivity-gap) | 不能归因于新界面，更不证明纸张拟物是多数人的偏好 |
| Duolingo | 2026 Q2股东信第8页：58.7M DAU，140.6M MAU。[原始股东信](https://investors.duolingo.com/static-files/3c8277ee-bc94-4f5d-9b77-0db3e46f88b8) | 不能把整个增长归因于视觉，也不能把2022截图视为2026全部界面 |

没有找到可核实的Obsidian官方总用户数，本报告不采用外部“百万用户”估算或插件下载量代替人数。也没有给不同口径的数据排序。

这些产品证明：内容型工具和强插画的学习产品都能获得广泛采用。稳妥的首套选择需要进一步看任务、阅读方式和操作复杂度。

## 4. 七个产品的具体观察

### Notion：可借鉴内容组织，不能照搬搭建负担

官方帮助呈现侧栏分组和页面组织；手机将多列内容转为单列，悬停操作改成可见入口。适合资料、笔记和记录回看；不宜让用户必须搭建复杂工作区才能开始学习。此处是帮助文核对，未登录实测。[移动端说明](https://www.notion.com/help/notion-for-mobile)、[官方侧栏示例图](https://images.ctfassets.net/spoqsaf9291f/2tpJheiXLOwBH9ZdZGnQt3/514bd06e33972f166580fa5c50bcdbdf/Group_61.png)

### Todoist：今日安排最直接的参照

已看过的中文官方图以浅底、任务行、轻分隔和局部强调组织“今天”；桌面侧栏与手机输入界面各有清晰重心。帮助文也说明不同设备的导航处理。值得借鉴任务主次与就近动作，不借用勾选来表示能力掌握。[导航说明](https://www.todoist.com/help/todoist/features/customize-the-sidebar-and-navigation-menu-in-todoist-S9JLTYqZV)、[中文界面图](https://www.todoist.com/_astro/headerui.zh-CN.CrOXYMpL.png)

### NotebookLM：与学习室最接近的内容关系

2024-12-13改版把来源、对话和整理产出分区，面板可展开配合阅读。官方三栏图已视觉核对：正文占主体，参考内容独立，关键生成动作有明显强调。借鉴职责分离和来源回看，不把三栏硬塞进手机，也不因此改变已确认导航。[改版说明及动态图](https://blog.google/innovation-and-ai/models-and-research/google-labs/notebooklm-new-features-december-2024/)、[2025移动端发布](https://blog.google/innovation-and-ai/products/notebooklm-app/)

### Linear：学习精细层级，不复制小字号和高密度

2026-03-12设计团队解释了弱化非当前导航、减少多余装饰和统一操作位置的调整。本次看过官方导航前后对照。重点是把注意力留给当前工作；微小文字和大量紧密控件不宜照搬到手机长篇学习。[2026改版原文](https://linear.app/now/behind-the-latest-design-refresh)、[2024设计过程](https://linear.app/now/how-we-redesigned-the-linear-ui)

其2025移动端也采用Liquid Glass，说明“内容简洁”和“导航有材料效果”可以共存，不应把某产品贴成永恒不变的单一风格。[移动端设计说明](https://linear.app/now/linear-liquid-glass)

### Obsidian：保留阅读空间，不把图谱变成默认首页

2022年1.0资料作为历史基线；2025-12-10手机早期访问版说明滚动阅读时收起导航、侧栏动作下移。本次依据官方说明核对，未声称当前所有用户都使用该版本。可借鉴阅读/编辑状态和按需工具，不能把插件、标签页、关系图全部常驻。[1.0介绍](https://obsidian.md/1.0)、[手机改版](https://obsidian.md/changelog/2025-12-10-mobile-v1.11.0/)

### Goodnotes：实际界面不等于“全站纸质纹理”

2025-09-23文章展示文字文档、白板、数学辅助和选中对象工具。本次看过文字文档与数学应用示例：主体是清楚的白色内容区，工具围绕内容出现。可借鉴阅读面和情境工具，不把手写笔工具栏当作对话/代码学习的通用结构。示例主要是大屏，手机细节未完整验证。[官方改版与截图](https://www.goodnotes.com/blog/the-new-goodnotes)

### Duolingo：证明鲜明表达也能成立，但学习形态不同

2022设计说明中的角色、彩色路径节点和下一步引导针对课程式推进。可借鉴清晰下一步与复习融入流程；不能将开放式深度学习压成固定关卡，也不能用连胜、徽章替代成果依据。本次不把历史设计说明当当前全端实测。[路径改版说明](https://blog.duolingo.com/new-duolingo-home-screen-design/)

### 中文产品补充与未采纳的证据

腾讯ima官方介绍覆盖资料、问答与写作；飞书官方帮助介绍内容类型和入口。它们有本地语境参考价值，但本次自动读取飞书正文不完整，ima定位到的图标不足以代表实际工作区。两者不计入已完成的应用视觉核对，也不据营销描述推导风格受欢迎程度。[ima官方页](https://ima.tencent.com/download)、[飞书官方帮助](https://www.feishu.cn/hc/zh-CN/articles/629777077520-快速上手云文档-新版)

## 5. 研究给出的约束与反证

**简洁需要保留可操作线索。** NN/g的2017实验包含71人、9组网页；弱点击提示使定位目标的时间平均增加22%。这是目标查找实验，不是整段学习效率测量，不能把数字外推成Nautilus的提升承诺。[实验方法与结果](https://www.nngroup.com/articles/flat-ui-less-attention-cause-uncertainty/)

Flat 2.0是既有术语，指以平面表达为主、保留有意义的深度和层次；不是本次发明的新风格名。定义材料发表于2015年，用于解释术语，不作为2026流行度证明。[术语与案例](https://www.nngroup.com/articles/flat-design/)、[实践建议](https://www.nngroup.com/articles/flat-design-best-practices/)

**克制不等于抹掉重点。** Google公开46项研究、18,000余参与者；部分任务关键控件定位最高快4倍，也报告破坏熟悉结构会损害可用性。这是厂商研究摘要，不能推出低饱和更好或任何Expressive页面都快4倍。[原始研究说明](https://design.google/library/expressive-material-design-google-research)

**视觉完成不能只看截图。** 建议用实际内容核对文字对比、触控和缩放。WCAG一般正文对比要求4.5:1；AA目标大小规则为24×24 CSS px并有间距等例外，不能把它当手机舒适尺寸。关键触控建议取更宽裕目标，具体尺寸在设计中验证。[文字对比](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)、[目标大小](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)

## 6. 首套风格建议如何具体落地

以下是研究建议，不是已经确认的视觉规格：

| 方面 | 首套建议 | 具体排除的误用 |
| --- | --- | --- |
| 背景与正文 | 稳定、低干扰的内容表面，正文拥有足够对比 | 不在长文、公式、代码后铺纹理、动态光斑或大面积透明材料 |
| 强调色 | 一个主强调方向，配合功能性状态色；优先强调继续、开始、发送和选择状态 | 不给每个同级模块随机上色，也不把所有按钮弱化成灰字 |
| 层次 | 用字号、字重、间距、表面差异组织；浮层用必要的边界/阴影 | 不做整页卡片套卡片或纯装饰大阴影 |
| 字体 | 先选择适合中文长文的正文和界面字；代码单独等宽，公式验证基线与字号 | 不直接照搬英文展示字体，或把桌面14px控件字号当手机学习正文 |
| 导航和动作 | 使用熟悉的带标签入口；当前项、按下、禁用和焦点可辨识 | 不以“极简”为由隐藏用户必须猜的功能 |
| 首页 | 保留已确认“接着上次学 → 今日学习 → 老师”层级；续学主动作突出，安排偏列表，老师紧凑 | 不改成营销大标题、数据仪表盘或卡通关卡地图 |
| 学习室 | 重点检验长对话、来源、公式、代码和输入区；辅助内容按需展开 | 不把官网宣传页的巨型渐变、发光边框作为日常阅读面 |
| 质感与动效 | 先服务层级、状态与反馈，保留适量个性 | 不把完整Liquid Glass物理效果、连续装饰动画设为首套前提 |

主参照次序建议：**Material 3提供完整规则 → Todoist校对首页安排 → Notion/NotebookLM校对内容空间 → Fluent 2校对桌面与状态细节。** 不是拼贴各家的按钮样式：最终仍需统一成学海无涯的一套字号、间距、表面和组件规则。

强插画、完整玻璃质感、纸张拟物或更实验性的视觉表达，不因本报告永久排除；只是没有足够理由把它们作为当前第一套的整体基线。多套风格改变排布的问题继续按作者要求留后。

## 7. 下一步与尚未决定的事项

1. 作者审阅是否接受“现代扁平化、适度层次，Material 3为主要基线”的首套方向与上述实际产品参照。
2. 方向接受后，用已确认首页内容制作一套具体视觉稿；再用一段真实长度的中文学习内容、公式和代码检查阅读表现。具体品牌色、字体和圆角在这时决定，不先重新做三套凭空命名的风格。
3. Penpot目标文件仍须核实；本次没有创建或改写设计文件，没有修改业务UI或试用环境。
4. 老师创建、重命名的具体交互、高度自定义展示及多套风格的排布差异继续留待各自详细设计。

验收建议关注：能否快速找到继续学习与今日动作；中文长文阅读是否舒适；辅助文字是否清楚；公式/代码是否溢出；手机输入时是否遮挡；当前状态、权限与来源能否按需确认。这些检查验证具体设计，不能用本报告或竞品用户数替代作者的界面验收。

## 8. 本轮执行记录

- 一名限定范围worker查五个产品的一手资料，主Agent核对关键来源并补充平台体系、研究、区域线索及实际截图；没有递归委派。
- 研究截图与只读浏览脚本保存在忽略的临时研究目录，不进入Git；报告只保留公开来源链接。未读取真实学习正文或模型凭据，未调用产品内真实模型。
- 浏览器核对使用公开页面，无登录或产品内操作。部分页面有Cookie遮挡，截图仅用于辨识可见界面；不声称完整全端验收。
- 本报告与产品决定/开发状态一起本地提交；无代码、迁移、依赖安装、服务重启或打包。
