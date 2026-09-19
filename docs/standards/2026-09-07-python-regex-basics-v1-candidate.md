# 候选标准包：Python 正则表达式基础 v1

| 项目 | 内容 |
| --- | --- |
| 状态 | **candidate**，未审核 |
| 版本 | 1 |
| 建议领域 | Python 正则表达式基础 |
| 适用范围 | 能在不查阅资料的情况下解释并编写基础 Python 正则表达式 |
| 主要来源 | Python 官方文档 `re` 模块 |
| 来源地址 | https://docs.python.org/3/library/re.html |
| 建议审核人 | 产品作者 / 领域负责人 |
| 创建日期 | 2026-09-07 |
| 结论 | 待确认；确认前不得绑定到正式学习委托 |

## 1. 推荐理由

- 范围足够窄，适合首个纵切片。
- 语义明确，容易拆成可验证的维度。
- 可以同时支持文本说明、代码示例和确定性检查。
- 官方文档稳定，来源可追溯。
- 与当前仓库的技术语境一致，便于后续用确定性测试验证。

## 2. 建议的可验证成果

> 学习者能够在不查阅资料的情况下，解释并编写基础 Python 正则表达式，用于匹配文本中的字面量、字符类、边界、量词和分组。

### 2.1 对象

- Python `re` 模块中的基础正则表达式语法。

### 2.2 行为

- 解释常见正则表达式成分的含义。
- 编写能匹配指定文本模式的基础正则表达式。
- 说明匹配结果和边界情况。

### 2.3 情境

- 本地学习与代码实践。
- 不要求覆盖回溯、性能优化或复杂嵌套语法。

## 3. 建议的验收维度

### 3.1 语法语义

**目标**：能解释字面量、字符类、锚点、量词和分组的作用。

**证据要求**：

- 至少 1 次 `semantic_analysis`
- 条件：`independent`
- 最低数量：1

### 3.2 应用能力

**目标**：能根据给定匹配任务编写正确的基础正则表达式。

**证据要求**：

- 至少 1 次 `deterministic_check`
- 条件：`independent`
- 最低数量：1

### 3.3 独立解释

**目标**：能不依赖提示解释一个正则表达式的匹配行为和边界情况。

**证据要求**：

- 至少 1 次 `independent_review`
- 条件：`independent`
- 最低数量：1

## 4. 建议的配方 JSON

```json
{
  "dimensions": [
    {
      "id": "syntax_semantics",
      "label": "正则表达式语法语义",
      "requirements": [
        {
          "method": "semantic_analysis",
          "condition": "independent",
          "minimum": 1
        }
      ]
    },
    {
      "id": "application",
      "label": "基础正则表达式应用",
      "requirements": [
        {
          "method": "deterministic_check",
          "condition": "independent",
          "minimum": 1
        }
      ]
    },
    {
      "id": "independent_explanation",
      "label": "独立解释匹配行为",
      "requirements": [
        {
          "method": "independent_review",
          "condition": "independent",
          "minimum": 1
        }
      ]
    }
  ]
}
```

## 5. 边界与限制

- 只覆盖 Python `re` 的基础语法，不覆盖复杂回溯、性能优化或所有高级特性。
- 不要求学习者记住所有旗标或所有转义细节。
- 不把“能写出答案”直接等同于“稳定掌握”。
- 本包在用户确认前保持 `candidate`，不参与正式状态派生。

## 6. 待用户确认的问题

1. 是否接受“Python 正则表达式基础”作为首个窄领域？
2. 是否接受上述三个验收维度？
3. 是否接受将本包从 `candidate` 升级为 `approved`？
