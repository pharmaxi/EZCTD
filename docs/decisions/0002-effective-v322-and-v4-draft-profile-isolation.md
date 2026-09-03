# ADR-0002：现行 eCTD V3.2.2/V1.1 与 eCTD v4.0 征求意见稿严格隔离

- Status: Accepted
- Date: 2026-09-03
- Scope: Regulatory source model, rule packs, validators, data model evolution

## Context

中国 CDE 于 2026-01-15 发布 eCTD V3.2.2 配套技术文件 V1.1，并自 2026-03-01 起施行。EZCTD 当前已回源核验的 PDF 规则 6.1–6.26、技术规范和附件包均属于该现行体系。

CDE 又于 2026-05-27 公开征求《eCTD v4.0指导原则》意见，并提供指导原则、受控词汇、验证标准、起草说明和反馈表。该材料属于中国区域实施的征求意见稿，不是现行 V3.2.2/V1.1 的替代规则，也不是已经生效的生产规范。

V3.2.2 与 v4.0 的差异不仅是目录模板或 XML 版本变化。v4.0 涉及新的信息模型、标识符、文档引用/复用、context of use、submission unit、受控词汇和生命周期表达。把两者放进同一个可变规则集合会造成以下风险：

1. 征求意见稿污染现行验证结果；
2. 同名概念在两个体系中语义不同却被覆盖；
3. PDF 规则严重程度被错误继承；
4. 对现有项目产生无法解释的结果漂移；
5. 最终版 v4.0 发布后无法重现当时的草案研究状态。

## Decision

### 1. 现行生产研究基线

使用独立 profile：

```text
cn-cde-ectd-v3.2.2-v1.1
```

其 PDF 子 profile 为：

```text
cn-cde-ectd-v3.2.2-v1.1-pdf
```

只有正式生效的 CDE 文件、其冻结字节哈希、官方验证软件的黑盒观察和经审查的产品安全护栏，才可进入该 profile。

### 2. v4.0 草案研究基线

使用独立 profile：

```text
cn-cde-ectd-v4.0-draft-2026-05-27
```

固定属性：

```text
profile_status = draft_research_only
runtime_enabled = false
```

该 profile 只能用于：

- 固化官方征求意见材料；
- 解析数据模型与受控词汇；
- 做 V3.2.2→v4.0 差异研究；
- 提前验证中性基础设施是否可扩展；
- 记录待最终文件确认的问题。

不得用于：

- 判断现行申报资料是否合规；
- 修改 6.1–6.26 的规则身份、严重程度或适用性；
- 生成宣称可正式递交的中国 v4.0 序列；
- 把草案验证信息展示成正式 CDE 错误；
- 自动迁移真实项目。

### 3. 禁止规则继承

两个 profile 之间不进行隐式继承。允许共享的只有监管中性的能力：

- 来源登记、哈希和不可变证据；
- 安全 XML 解析；
- 文件/文档依赖图；
- 受控词汇加载器；
- 证据报告格式；
- worker 隔离和资源上限；
- 通用 UUID、标识符和引用值对象；
- 测试和差异基础设施。

任何共享能力不得自带区域规则或默认严重程度。

### 4. 规则身份必须包含 profile 和来源

规则或验证信息的稳定身份至少包含：

```text
jurisdiction
standard_family
profile_version
rule_id
source_document_hash
```

相同显示标题不代表相同规则。

### 5. 最终版 v4.0 必须重新立项固化

中国正式 v4.0 文件发布后：

1. 新建正式 profile，不覆盖草案 profile；
2. 重新下载并固定全部正式文件及哈希；
3. 做草案→正式的逐项差异；
4. 对数据模型、验证规则和受控词汇分别审查；
5. 建立官方实现/验证器黑盒证据；
6. 经过单独 ADR 后才允许 `runtime_enabled=true`。

## Consequences

### Positive

- 现行 V3.2.2 结果可重复，不受草案变化影响；
- v4.0 可以提前研究而不产生虚假合规结论；
- 最终版发布时有完整草案历史和差异基础；
- 迫使代码以 profile 为边界，而不是散落条件判断。

### Costs

- 需要维护两套独立来源清单和数据模型；
- UI、报告、数据库和测试都必须显式显示 profile；
- v4.0 研究成果不能直接复制到生产规则；
- 需要为跨 profile 通用类型设计清晰边界。

## Verification

本 ADR 的自动化约束为：

- v4 草案 manifest 必须保持 `runtime_enabled=false`；
- `must_not_influence` 必须列出当前 V3.2.2 profile；
- CI 不得把 v4 草案规则载入现行 PDF 观察器；
- v4 原始文件和当前 V1.1 文件分别记录 SHA-256；
- 任何启用 v4 runtime 的提交必须同时修改本 ADR 或新增替代 ADR。

## Official sources

- CDE eCTD 专栏：`https://www.cde.org.cn/ectd/index`
- eCTD技术规范V1.1：`https://www.cde.org.cn/ectd/guideDownLoads/eCTDJSGFV1.1.pdf`
- eCTD技术规范V1.1附件包：`https://www.cde.org.cn/ectd/guideDownLoads/eCTDJSGFV1.1FJ.zip`
- 中国 eCTD v4.0 征求意见通知：`https://www.cde.org.cn/main/news/viewInfoCommon/7898f68946d8e8e44d074657c7112002`
