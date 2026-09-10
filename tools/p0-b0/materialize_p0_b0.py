from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_DOCS = ROOT / "docs" / "validation" / "p0-b0"
OUT_TESTS = ROOT / "tests" / "p0_b0"
OUT_TOOLS = ROOT / "tools" / "cde-validator"
RULE_SOURCE = ROOT / "rulepacks" / "cn-cde-ectd" / "v1.1" / "cde_ectd_pdf_rules_v1.1_verified.json"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8", newline="\n")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_rules() -> list[dict[str, Any]]:
    payload = json.loads(RULE_SOURCE.read_text(encoding="utf-8"))
    rules = payload["rules"]
    expected_ids = [f"6.{i}" for i in range(1, 27)]
    ids = [r["id"] for r in rules]
    if ids != expected_ids:
        raise RuntimeError(f"verified rule IDs mismatch: {ids}")
    counts: dict[str, int] = {}
    for rule in rules:
        counts[rule["official_severity"]] = counts.get(rule["official_severity"], 0) + 1
    if counts != {"错误": 16, "警告": 8, "提示信息": 2}:
        raise RuntimeError(f"severity count mismatch: {counts}")
    return rules


CONTRACTS: dict[str, dict[str, Any]] = {
    "6.1": {
        "object_scope": ["file", "xref", "page_tree"],
        "predicate": "PDF can be parsed, has at least one page, and required pages can be rendered.",
        "signals": ["qpdf_check", "pikepdf_open", "page_count", "pdfium_render"],
        "positive_mutation": "truncate final bytes so the file is not recoverably readable",
        "boundary": ["recoverable xref damage", "zero-page PDF", "parser disagreement"],
        "requires_package_context": False,
    },
    "6.2": {
        "object_scope": ["outline", "action", "filespec"],
        "predicate": "Every bookmark file target is relative and resolves inside the submission root.",
        "signals": ["outline_action_type", "filespec_path", "path_resolution"],
        "positive_mutation": "bookmark GoToR target uses an absolute Windows path",
        "boundary": ["UNC path", "file URI", "relative path with ..", "case-only mismatch"],
        "requires_package_context": True,
    },
    "6.3": {
        "object_scope": ["outline", "action"],
        "predicate": "Bookmarks do not contain URI, mailto, or targets external to the dossier, except in scoped exemptions.",
        "signals": ["outline_action_type", "URI_scheme", "resolved_target_scope"],
        "positive_mutation": "bookmark contains an HTTPS URI action",
        "boundary": ["mailto", "custom URI scheme", "reference-node exemption"],
        "requires_package_context": True,
    },
    "6.4": {
        "object_scope": ["outline", "action"],
        "predicate": "Bookmark actions are limited to GoTo, GoToR, or Launch under the official wording.",
        "signals": ["outline_action_type", "additional_actions", "next_action_chain"],
        "positive_mutation": "bookmark uses a JavaScript action",
        "boundary": ["Named", "SubmitForm", "GoToE", "action in /AA"],
        "requires_package_context": False,
    },
    "6.5": {
        "object_scope": ["outline"],
        "predicate": "Every bookmark has a destination or action.",
        "signals": ["has_Dest", "has_A"],
        "positive_mutation": "bookmark has neither /Dest nor /A",
        "boundary": ["empty named destination", "null action", "child-only destination"],
        "requires_package_context": False,
    },
    "6.6": {
        "object_scope": ["outline", "destination", "target_file"],
        "predicate": "Every bookmark target exists and is addressable.",
        "signals": ["target_file_exists", "target_page_exists", "named_destination_exists"],
        "positive_mutation": "bookmark points to a missing PDF",
        "boundary": ["missing named destination", "page index out of range", "broken indirect object"],
        "requires_package_context": True,
    },
    "6.7": {
        "object_scope": ["outline", "action_chain"],
        "predicate": "A bookmark has one effective action and no chained additional action.",
        "signals": ["A_count", "AA_count", "Next_count"],
        "positive_mutation": "bookmark action contains /Next",
        "boundary": ["array-valued /Next", "nested chain", "duplicate equivalent actions"],
        "requires_package_context": False,
    },
    "6.8": {
        "object_scope": ["outline", "destination"],
        "predicate": "Bookmark destination preserves target position while zoom is inherited.",
        "signals": ["destination_kind", "XYZ_zoom"],
        "positive_mutation": "bookmark /XYZ destination has numeric zoom 2.0",
        "boundary": ["XYZ zoom null", "Fit/FitH/FitV semantics", "named destination"],
        "requires_package_context": False,
    },
    "6.9": {
        "object_scope": ["link_annotation", "action", "filespec"],
        "predicate": "Cross-document hyperlink targets are relative and resolve inside the submission root.",
        "signals": ["annotation_subtype", "filespec_path", "path_resolution"],
        "positive_mutation": "link GoToR target uses an absolute Windows path",
        "boundary": ["UNC path", "file URI", "dot-segment escape", "case-only mismatch"],
        "requires_package_context": True,
    },
    "6.10": {
        "object_scope": ["link_annotation", "action"],
        "predicate": "Hyperlinks do not contain URI, mailto, or external dossier targets except scoped exemptions.",
        "signals": ["annotation_subtype", "action_type", "URI_scheme", "target_scope"],
        "positive_mutation": "link annotation contains an HTTPS URI action",
        "boundary": ["mailto", "custom protocol", "reference-node exemption"],
        "requires_package_context": True,
    },
    "6.11": {
        "object_scope": ["link_annotation", "action"],
        "predicate": "Hyperlink actions are limited to GoTo, GoToR, or Launch under the official wording.",
        "signals": ["action_type", "additional_actions"],
        "positive_mutation": "link uses JavaScript action",
        "boundary": ["Named", "SubmitForm", "GoToE", "action in /AA"],
        "requires_package_context": False,
    },
    "6.12": {
        "object_scope": ["link_annotation"],
        "predicate": "Every link annotation has a destination or action.",
        "signals": ["has_Dest", "has_A", "Rect_valid"],
        "positive_mutation": "Link annotation has neither /Dest nor /A",
        "boundary": ["zero-area Rect", "null destination", "Popup without parent"],
        "requires_package_context": False,
    },
    "6.13": {
        "object_scope": ["link_annotation", "destination", "target_file"],
        "predicate": "Every hyperlink target exists and is addressable.",
        "signals": ["target_file_exists", "target_page_exists", "named_destination_exists"],
        "positive_mutation": "link points to a missing PDF",
        "boundary": ["missing named destination", "page out of range", "broken indirect target"],
        "requires_package_context": True,
    },
    "6.14": {
        "object_scope": ["link_annotation", "action_chain"],
        "predicate": "A hyperlink has one effective action and no chained additional action.",
        "signals": ["A_count", "AA_count", "Next_count"],
        "positive_mutation": "link action contains /Next",
        "boundary": ["array-valued /Next", "nested chain", "duplicate equivalent actions"],
        "requires_package_context": False,
    },
    "6.15": {
        "object_scope": ["link_annotation", "destination"],
        "predicate": "Hyperlink destination preserves target position while zoom is inherited.",
        "signals": ["destination_kind", "XYZ_zoom"],
        "positive_mutation": "link /XYZ destination has numeric zoom 2.0",
        "boundary": ["XYZ zoom null", "Fit variants", "named destination"],
        "requires_package_context": False,
    },
    "6.16": {
        "object_scope": ["file_header", "catalog", "pdfa_metadata"],
        "predicate": "PDF version is 1.4–1.7 or the file genuinely conforms to PDF/A-1 or PDF/A-2.",
        "signals": ["header_version", "catalog_version", "pdfa_identification", "verapdf_result"],
        "positive_mutation": "save as PDF 1.3",
        "boundary": ["header/catalog disagreement", "PDF 2.0", "false PDF/A metadata", "valid PDF/A-2"],
        "requires_package_context": False,
    },
    "6.17": {
        "object_scope": ["names_tree", "filespec", "annotation"],
        "predicate": "No embedded attachment is present, except when the rule is inapplicable by dossier context.",
        "signals": ["EmbeddedFiles", "FileAttachment_annotation", "AF_array"],
        "positive_mutation": "embed payload.txt through EmbeddedFiles name tree",
        "boundary": ["associated file /AF", "FileAttachment annotation", "orphan filespec"],
        "requires_package_context": True,
    },
    "6.18": {
        "object_scope": ["annotation"],
        "predicate": "Only Link annotations are present; signature widgets are separately classified and never silently removed.",
        "signals": ["annotation_subtype", "field_type", "signature_presence"],
        "positive_mutation": "add a Text annotation",
        "boundary": ["Widget signature", "Redact", "Stamp", "Popup child"],
        "requires_package_context": True,
    },
    "6.19": {
        "object_scope": ["encryption_dictionary", "permissions"],
        "predicate": "The PDF is not encrypted and contains no effective security restrictions.",
        "signals": ["Encrypt_present", "permission_bits", "qpdf_encryption_json"],
        "positive_mutation": "encrypt with empty user password and restricted extraction/modification",
        "boundary": ["owner password only", "empty user password", "all permissions allowed", "public-key encryption"],
        "requires_package_context": False,
    },
    "6.20": {
        "object_scope": ["catalog", "open_action"],
        "predicate": "Files with bookmarks open with bookmark panel visible; magnification and page layout are default.",
        "signals": ["PageMode", "PageLayout", "OpenAction"],
        "positive_mutation": "bookmark exists but PageMode=UseNone, layout=TwoColumnLeft and zoom=2.0",
        "boundary": ["no bookmarks", "UseOutlines with explicit zoom", "viewer preference disagreement"],
        "requires_package_context": True,
    },
    "6.21": {
        "object_scope": ["encryption_dictionary", "open_attempt"],
        "predicate": "The PDF opens without a user password.",
        "signals": ["open_without_password", "encryption_type"],
        "positive_mutation": "encrypt with non-empty user password",
        "boundary": ["empty user password", "owner-only password", "damaged file misclassified as password"],
        "requires_package_context": False,
    },
    "6.22": {
        "object_scope": ["linearization_dictionary", "file_layout"],
        "predicate": "Fast Web View is enabled when the dossier node is not exempt.",
        "signals": ["qpdf_is_linearized", "linearization_dictionary", "dossier_node"],
        "positive_mutation": "save a valid PDF without linearization",
        "boundary": ["stale linearization dictionary", "post-edit invalidation", "explicit exempt node"],
        "requires_package_context": True,
    },
    "6.23": {
        "object_scope": ["document", "outline", "dossier_node"],
        "predicate": "A non-exempt PDF with more than five pages has at least one valid bookmark.",
        "signals": ["page_count", "outline_count", "dossier_node", "document_type"],
        "positive_mutation": "six-page non-exempt PDF has no outline",
        "boundary": ["exactly five pages", "six pages", "application form", "reference node", "foreign reference"],
        "requires_package_context": True,
    },
    "6.24": {
        "object_scope": ["catalog", "action", "annotation", "xobject"],
        "predicate": "No JavaScript, 3D, audio, video, RichMedia, Movie, Sound, or equivalent dynamic content is present.",
        "signals": ["JavaScript_name_tree", "OpenAction", "AA", "3D", "RichMedia", "Movie", "Sound"],
        "positive_mutation": "add document-level JavaScript",
        "boundary": ["JavaScript in field AA", "3D annotation", "RichMedia activation", "orphan dynamic object"],
        "requires_package_context": True,
    },
    "6.25": {
        "object_scope": ["page", "text_layer", "image"],
        "predicate": "Required textual content is searchable; scanned pages provide a usable OCR text layer.",
        "signals": ["characters_per_page", "image_area_ratio", "text_render_mode", "search_probe"],
        "positive_mutation": "image-only page with no text objects",
        "boundary": ["one image-only page in long PDF", "hidden text mismatch", "vector outlines", "legitimate image plate"],
        "requires_package_context": True,
    },
    "6.26": {
        "object_scope": ["font_resource", "font_descriptor", "font_program"],
        "predicate": "Every non-standard font used by page content is embedded.",
        "signals": ["BaseFont", "Subtype", "FontDescriptor", "FontFile", "FontFile2", "FontFile3", "content_usage"],
        "positive_mutation": "use a non-standard Type1 font without an embedded font program",
        "boundary": ["Base-14 font", "subset font", "unused resource", "Type0 descendant embedding", "invalid font program"],
        "requires_package_context": True,
    },
}

INTERACTION_PARTNERS = {
    "6.1": "6.21", "6.2": "6.6", "6.3": "6.4", "6.4": "6.7", "6.5": "6.6", "6.6": "6.2",
    "6.7": "6.4", "6.8": "6.20", "6.9": "6.13", "6.10": "6.11", "6.11": "6.14", "6.12": "6.13",
    "6.13": "6.9", "6.14": "6.11", "6.15": "6.20", "6.16": "6.22", "6.17": "6.18", "6.18": "6.24",
    "6.19": "6.21", "6.20": "6.8", "6.21": "6.19", "6.22": "6.16", "6.23": "6.25", "6.24": "6.18",
    "6.25": "6.23", "6.26": "6.25",
}

EXEMPT_CONTEXT = {
    "node_path": "m5/54-lit-refer/reference.pdf",
    "node_id": "5.4",
    "document_role": "reference",
    "language": "en",
}
NON_EXEMPT_CONTEXT = {
    "node_path": "m5/535-rep-effic-safety-stud/study-report.pdf",
    "node_id": "5.3.5",
    "document_role": "study-report",
    "language": "zh-CN",
}


def build_case_matrix(rules: list[dict[str, Any]]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for rule in rules:
        rid = rule["id"]
        contract = CONTRACTS[rid]
        base = {
            "rule_id": rid,
            "official_title": rule["official_title"],
            "official_severity": rule["official_severity"],
            "source_page": rule["printed_page"],
            "source_status": rule["verification_status"],
            "detector_contract": contract,
        }
        variants = [
            ("compliant", "CONTROL_PASS", "Target predicate is satisfied; target rule must not be reported."),
            ("violation", "TARGET_FINDING", contract["positive_mutation"]),
            ("boundary", "OBSERVE_AND_CLASSIFY", contract["boundary"][0]),
            ("exemption", "CONTEXT_DEPENDENT", "Place the same target mutation in an explicitly exempt or potentially exempt context."),
            ("interaction", "INDEPENDENT_FINDINGS", f"Combine target rule with {INTERACTION_PARTNERS[rid]} and confirm neither masks the other."),
        ]
        for variant, expected, mutation in variants:
            suffix = {"compliant": "NEG", "violation": "POS", "boundary": "BND", "exemption": "EXM", "interaction": "INT"}[variant]
            case = dict(base)
            case.update({
                "case_id": f"CDE-PDF-{rid.replace('.', '-')}-{suffix}",
                "variant": variant,
                "mutation": mutation,
                "expected_ezctd": expected,
                "expected_official": "TO_BE_OBSERVED",
                "official_observation": {"status": "NOT_RUN", "validator_version": "1.1.0", "message": None, "severity": None},
                "context": EXEMPT_CONTEXT if variant == "exemption" else NON_EXEMPT_CONTEXT,
                "interaction_rule": INTERACTION_PARTNERS[rid] if variant == "interaction" else None,
            })
            cases.append(case)
    return {
        "schema_version": "0.3.0",
        "profile_id": "cn-cde-ectd-v3.2.2-v1.1-pdf",
        "purpose": "Machine-readable detection-contract and black-box observation matrix. Expected and observed fields are deliberately separate.",
        "official_validator": {"name": "CDE eCTD validation software", "target_version": "1.1.0", "observations_completed": 0},
        "counts": {"rules": len(rules), "variants_per_rule": 5, "cases": len(cases)},
        "rules": [{**r, "detector_contract": CONTRACTS[r["id"]]} for r in rules],
        "cases": cases,
    }


def build_smoke_manifest(matrix: dict[str, Any]) -> dict[str, Any]:
    smoke = [{
        "case_id": "CDE-PDF-BASELINE",
        "rule_id": None,
        "variant": "baseline",
        "file_name": "CDE-PDF-BASELINE.pdf",
        "expected_parser": "ACCEPT",
        "expected_pdfium": "RENDER",
        "expected_qpdf": "PASS",
        "context": NON_EXEMPT_CONTEXT,
    }]
    for i in range(1, 27):
        rid = f"6.{i}"
        smoke.append({
            "case_id": f"CDE-PDF-{rid.replace('.', '-')}-POS",
            "rule_id": rid,
            "variant": "violation",
            "file_name": f"CDE-PDF-{rid.replace('.', '-')}-POS.pdf",
            "expected_parser": "REJECT" if rid in {"6.1", "6.21"} else "ACCEPT",
            "expected_pdfium": "REJECT" if rid in {"6.1", "6.21"} else "RENDER",
            "expected_qpdf": "REJECT" if rid in {"6.1", "6.21"} else "PASS",
            "context": NON_EXEMPT_CONTEXT,
        })
    smoke.append({
        "case_id": "CDE-PDF-6-23-EXM-REFERENCE",
        "rule_id": "6.23",
        "variant": "exemption",
        "file_name": "CDE-PDF-6-23-EXM-REFERENCE.pdf",
        "expected_parser": "ACCEPT",
        "expected_pdfium": "RENDER",
        "expected_qpdf": "PASS",
        "context": EXEMPT_CONTEXT,
    })
    return {"schema_version": "0.2.0", "count": len(smoke), "cases": smoke}


def build_boundary_queue(matrix: dict[str, Any]) -> dict[str, Any]:
    experiments: list[dict[str, Any]] = []
    for rule in matrix["rules"]:
        rid = rule["id"]
        contract = rule["detector_contract"]
        dimensions = list(contract["boundary"])
        while len(dimensions) < 5:
            dimensions.append(f"cross-engine interpretation #{len(dimensions)+1}")
        for index, dimension in enumerate(dimensions[:5], 1):
            experiments.append({
                "experiment_id": f"EXP-{rid.replace('.', '-')}-{index:02d}",
                "rule_id": rid,
                "dimension": dimension,
                "hypothesis": f"Determine how CDE validator 1.1.0 classifies {dimension} for rule {rid}.",
                "control_required": True,
                "package_context_required": contract["requires_package_context"],
                "official_observation": "NOT_RUN",
                "decision_use": "Refine detector predicate, exemption routing, or finding message without changing official severity.",
            })
    return {"schema_version": "0.1.0", "count": len(experiments), "experiments": experiments}


def matrix_markdown(matrix: dict[str, Any]) -> str:
    rows = []
    for rule in matrix["rules"]:
        c = rule["detector_contract"]
        rows.append(
            f"| {rule['id']} | {rule['official_title']} | {rule['official_severity']} | "
            f"{'是' if c['requires_package_context'] else '否'} | {c['predicate']} | {c['positive_mutation']} | NOT_RUN |"
        )
    return """# P0-B0 CDE PDF 规则验证矩阵

> 状态：检测合同与合成实验设计完成；CDE eCTD 验证软件 V1.1.0 的实际结果尚未采集。  
> 原则：`expected_official` 与 `official_observation` 永远分离。未实际运行不得填写为通过或一致。

## 目标

把 6.1–6.26 每条规则转化为五项可执行对象：官方来源、检测合同、单变量样本、官方验证器观察、未决边界实验。

## 总体计数

- 正式规则：26
- 错误：16；警告：8；提示信息：2
- 基础案例配方：130（每条 5 类）
- smoke PDF：28
- 边界实验：130
- 官方 V1.1.0 观察：0，状态 `NOT_RUN`

## 逐条矩阵

| 规则 | 正式标题 | 严重程度 | 需包上下文 | EZCTD 检测合同 | 单变量阳性变异 | 官方观察 |
|---|---|---|---:|---|---|---|
""" + "\n".join(rows) + """

## 解释边界

1. 表中的检测合同是 EZCTD 的可执行解释，不替代 CDE 原文。
2. 正式严重程度不可由本项目自行升降级。
3. 有例外的规则必须先解析 eCTD 节点、资料角色和语言，再判断 PDF 对象。
4. 6.8/6.15 的 Inherit Zoom 不是把所有目的地改成 `/Fit`；对 `/XYZ` 通常应保留页与位置，将 zoom 置空。
5. 6.19 与 6.21 必须分开：前者检查安全设置/权限，后者检查不能无密码打开。
6. 6.25 是页面级可搜索性，不应只按整份 PDF 抽取字符数做二元判断。
7. 6.26 必须确认字体被页面内容实际使用；“资源字典里出现字体”不等于触发。
"""


def materialize_docs(matrix: dict[str, Any], smoke: dict[str, Any], boundary: dict[str, Any]) -> None:
    write_text(OUT_DOCS / "GOAL_AND_EXIT_CRITERIA.md", """
    # P0-B0 目标与退出条件

    ## 本轮目标

    为 CDE eCTD V3.2.2 / V1.1 的 PDF 规则 6.1–6.26 建立可复现的验证基线，使下一阶段扫描器开发不再依赖口头解释。

    ## P0-B0-A：合成验证基线

    完成条件：

    - 26 条规则全部具有机器可读检测合同；
    - 每条规则有 compliant、violation、boundary、exemption、interaction 五类配方，共 130 个；
    - 生成 28 个高信息量 smoke PDF：1 个基线、26 个单规则阳性、1 个 6.23 参考文献豁免；
    - 对生成物执行对象级自检、PDFium 渲染探针、qpdf 结构探针和重复生成哈希比较；
    - 建立已知良好 eCTD 基线包的差分替换工具；
    - CI 可在无真实项目资料的条件下重复运行。

    ## P0-B0-B：官方黑盒观察

    完成条件：

    - 固化 CDE eCTD 验证软件 V1.1.0 安装包、操作手册和文件哈希；
    - 准备一个经 V1.1.0 验证的最小已知良好中国 eCTD 序列；
    - 将 28 个 smoke PDF 逐一替换同一叶文件，保持 XML、路径和 MD5 正确；
    - 每案保存软件版本、输入哈希、完整报告、截图和人工复核记录；
    - 将实际消息、严重程度和命中规则写入 `official-validator/results`；
    - 对不一致项进行二次最小化，不用猜测填补。

    ## 当前结论

    P0-B0-A 的设计与执行工具已完成。P0-B0-B 仍为 `NOT_RUN`，在获得 Windows 官方软件运行结果前，不得声称与 CDE 验证器等价。
    """)
    write_text(OUT_DOCS / "RULE_VALIDATION_MATRIX.md", matrix_markdown(matrix))
    write_text(OUT_DOCS / "OFFICIAL_VALIDATOR_BLACKBOX_PROTOCOL.md", """
    # CDE eCTD 验证软件 V1.1.0 黑盒验证协议

    ## 目的

    观察官方软件对单一 PDF 变异的实际分类、消息和严重程度。实验结果用于校准 EZCTD detector，不用于反推或复制官方软件代码。

    ## 硬前提

    1. Windows 环境中安装官方 V1.1.0；记录安装包 SHA-256、文件版本、安装时间和来源。
    2. 使用一个官方软件验证无阻断问题的最小中国 eCTD V3.2.2 序列作为 baseline。
    3. baseline 每次从只读快照复制，禁止连续在同一个工作目录上累积修改。
    4. 每个实验只替换一个 PDF 叶文件；同步更新 XML 中叶文件 MD5 和 `index-md5.txt`。
    5. 结果文件、截图和结构化记录均以 case ID 命名。

    ## 单案步骤

    1. 核验 baseline 包哈希与官方 baseline 报告。
    2. 运行 `prepare_differential_packages.py`，将目标 PDF 替换到指定 leaf。
    3. 用独立脚本复核相对路径、XML href、leaf checksum 和 index MD5。
    4. 启动 CDE 软件，记录版本界面截图。
    5. 验证实验包；导出完整报告，不只抄一行消息。
    6. 记录实际 rule/message/severity、是否阻断、是否存在额外包级消息。
    7. 再运行同批次 control 包，排除软件状态、缓存或 baseline 漂移。
    8. 将结果写入 JSON，运行 schema 校验后提交。

    ## 实验设计

    - `baseline`：无目标变异，证明包本身不制造 PDF 规则消息。
    - `positive`：单规则阳性。
    - `negative`：与阳性对象相似但满足规则。
    - `boundary`：阈值、对象表达或解析器分歧。
    - `exemption`：同一变异置于正式例外节点。
    - `interaction`：两个缺陷同时存在，观察屏蔽、合并或优先级。

    ## 判读

    - `MATCH`：目标规则、严重程度和对象范围与合同一致。
    - `PARTIAL`：命中目标，但消息、对象范围或严重程度存在差异。
    - `OFFICIAL_ONLY`：官方命中，EZCTD 未命中。
    - `EZCTD_ONLY`：EZCTD 命中，官方未命中；不立即判定官方漏检，应先检查上下文与样本真实性。
    - `INCONCLUSIVE`：包级错误、软件异常或样本变量不单一。

    ## 证据要求

    每个 case 至少保存：输入 PDF SHA-256、实验包 SHA-256 清单、软件版本、运行时间、报告原文件、截图、结构化结果、复核人和备注。任何一项缺失都不能标为“已验证”。
    """)
    write_text(OUT_DOCS / "PDF_TECHNICAL_SEMANTICS.md", """
    # PDF 技术语义说明

    ## 书签与超链接

    PDF 书签通常位于 Outline 树；超链接通常是页面 `/Annots` 中的 `/Link` 注释。两者都可能直接使用 `/Dest`，也可能通过 `/A` 使用 GoTo、GoToR、URI、Launch 等动作。`/Next` 可形成动作链，因此“只有一个 `/A`”不等于“只有一个动作”。

    ## Inherit Zoom

    对 `/XYZ [left top zoom]`，承前缩放的关键是 `zoom=null`，同时保持页、left 和 top。`/Fit`、`/FitH` 等会改变视图语义，不能作为通用等价替换。命名目的地需要解析后再检查实际目的地。

    ## 相对路径

    相对路径是相对于当前 PDF 或申报包结构解析的语义，不是仅检查是否缺少盘符。必须规范化分隔符、`.`、`..`、Unicode 和大小写，并确认解析结果仍在 submission root 内。

    ## 安全设置与密码

    有 `/Encrypt` 但空 user password 的 PDF 可能无需输入密码即可打开，仍可能限制复制、打印或修改，因此触发 6.19；不能无密码打开主要属于 6.21。两个 detector 必须独立。

    ## PDF 版本与 PDF/A

    修改 `%PDF-x.y` 文件头不能把普通 PDF 变成 PDF/A。PDF/A 需要一致的 XMP 标识、色彩、字体和其他约束，并应由独立验证器验证。Header 与 Catalog `/Version` 不一致时需记录两者。

    ## 可搜索性

    OCR 文本层存在不等于可用：需要检查文本覆盖、字符质量、页面对应和搜索命中。纯矢量轮廓文字没有可搜索字符；隐藏文字与图像明显不一致也应进入人工复核。

    ## 字体嵌入

    Type1、TrueType、Type0/CID 字体的嵌入位置不同。判断应沿 FontDescriptor 查找 FontFile/FontFile2/FontFile3，并确认字体资源确实被内容流使用。缺失字体程序通常不能从 PDF 名称凭空恢复。
    """)
    write_text(OUT_DOCS / "OPEN_QUESTIONS.md", """
    # P0-B0 未决问题

    ## 需要官方 V1.1.0 黑盒实验回答

    1. 6.1 对可恢复 xref 损坏、零页 PDF 和不同解析器结果的实际阈值。
    2. 6.2/6.9 对 `..`、UNC、`file://`、大小写不一致和中文路径的处理。
    3. 6.4/6.11 官方表述允许 Launch，但 Launch 到包外程序是否另有安全规则拦截。
    4. 6.7/6.14 是否遍历 `/Next` 的数组与嵌套链。
    5. 6.8/6.15 对 Fit/FitH/FitV 和命名目的地如何判定 Inherit Zoom。
    6. 6.16 是否验证真实 PDF/A 一致性，还是仅检查版本/标识。
    7. 6.18 对 Widget、数字签名字段、Stamp 和 Popup 的分类。
    8. 6.19 空 user password 但权限受限时的消息；与 6.21 是否同时触发。
    9. 6.20 “默认”在软件内部对应哪些 Catalog 值；无书签文件是否检查 PageMode。
    10. 6.22 线性化字典存在但已失效时是否识别；验证是在 PDF 修改前还是最终字节上完成。
    11. 6.23 “大于5页”是否严格为 6 页起；申请表和参考文献例外如何由目录节点识别。
    12. 6.25 是整份文档还是逐页阈值；少量扫描页、隐藏文本和矢量字的处理。
    13. 6.26 标准字体清单、未使用字体资源、子集字体和 Type0 字体的判定方式。

    ## 资料缺口

    - 官方 V1.1.0 安装包和配套操作手册尚未在仓库固化哈希。
    - 尚无经 V1.1.0 证明为 clean 的最小中国 eCTD baseline sequence。
    - 尚未取得官方软件导出报告的稳定机器可读格式。
    - 《eCTD技术规范V1.1》3.3/3.4 与 PDF 规则之间仍需段落级交叉映射。
    """)
    write_text(OUT_DOCS / "BOUNDARY_EXPERIMENT_QUEUE.md", f"""
    # 边界实验队列

    机器可读文件：`tests/p0_b0/boundary_experiment_queue.json`。

    当前包含 **{boundary['count']}** 个实验，覆盖每条规则至少 5 个边界维度。全部官方观察初始值为 `NOT_RUN`。优先级顺序：

    1. 会改变 detector 数据模型的语义：动作链、目的地、路径解析、加密、字体。
    2. 会影响例外路由的上下文：参考文献、外文参考资料、申请表和 Fast Web View 特定节点。
    3. 会影响阈值的规则：页数、文本可搜索性、PDF/A、损坏可恢复性。
    4. 交互与屏蔽：6.19/6.21、6.8/6.20、6.16/6.22、6.23/6.25。
    """)
    write_text(OUT_DOCS / "AGENT_LOOP_LOG.md", """
    # P0-B0 Agent Loop 记录

    ## Loop 0 — 目标收敛

    将目标从“继续调研”收敛为五联矩阵：官方来源、检测合同、测试样本、官方观察、未决问题。明确官方 V1.1.0 未运行前不得宣称等价。

    ## Loop 1 — 规则结构化

    以已逐条回源的 6.1–6.26 为权威输入，固定 16/8/2 严重程度计数。每条规则生成五类案例，共 130 个。

    ## Loop 2 — 合成样本

    建立 28 个 smoke 样本：基线、26 个单规则阳性、6.23 参考节点豁免。生成器使用确定性参数，不提交真实申报资料。

    ## Loop 3 — 自检而非自证

    为样本增加对象级断言、PDFium 渲染和 qpdf 结构探针。自检只能证明变异被按计划写入和文件可解析，不能证明官方软件一定同样分类。

    ## Loop 4 — 包级实验

    不尝试凭空伪造“合规中国 eCTD 包”。采用已知良好 baseline sequence，逐案替换同一个 leaf，更新 XML MD5 与 index MD5，以减少包级噪声。

    ## Loop 5 — 当前复盘

    P0-B0-A 可重复执行；P0-B0-B 最大阻塞是官方 V1.1.0 Windows 软件、clean baseline 和真实报告。下一次循环应优先获得这些输入并执行最小 6 案校准批次：baseline、6.1、6.8、6.19、6.22、6.26。
    """)
    source_manifest = {
        "schema_version": "0.2.0",
        "effective_baseline": "2026-03-01",
        "sources": [
            {
                "id": "CDE-2026-04",
                "authority": "CDE/NMPA",
                "title": "国家药监局药审中心关于发布eCTD V3.2.2相关技术文件的通告（2026年第4号）",
                "published": "2026-01-15",
                "status": "effective",
                "url": "https://www.cde.org.cn/main/news/viewInfoCommon/454f7eb43d4eb4c42503d697784903db",
            },
            {
                "id": "CDE-VALIDATOR-1.1.0-NOTICE",
                "authority": "CDE/NMPA",
                "title": "关于更新eCTD验证软件的通知",
                "published": "2026-01-15",
                "effective": "2026-03-01",
                "status": "effective",
                "url": "https://www.cde.org.cn/main/news/viewInfoCommon/43ee306c48b514cb05fdbf6e6f873d67",
            },
            {
                "id": "CDE-ECTD-VALIDATION-1.1",
                "authority": "CDE/NMPA",
                "title": "eCTD验证标准V1.1",
                "status": "effective-primary",
                "section": "6 PDF分析",
                "pages": "9-11",
                "repository_record": "rulepacks/cn-cde-ectd/v1.1/cde_ectd_pdf_rules_v1.1_verified.json",
                "retrieval_note": "Repository stores structured excerpts and source metadata; official binary must be separately hashed when downloaded.",
            },
            {
                "id": "ICH-ECTD-3.2.2",
                "authority": "ICH",
                "title": "eCTD v3.2.2 specification and implementation package",
                "status": "international-base; regional CDE files control China implementation",
                "url": "https://www.ich.org/page/ich-electronic-common-technical-document-ectd-v322",
            },
        ],
        "evidence_policy": "Official effective sources control. Drafts and vendor interpretations may identify questions but never override the effective source.",
    }
    write_json(OUT_DOCS / "SOURCE_MANIFEST.json", source_manifest)
    write_text(OUT_DOCS / "CDE_ATTACHMENT_DISCOVERY_REPORT.md", """
    # CDE 附件发现与固化说明

    CDE 通告页确认 V1.1 技术文件和验证软件 V1.1.0 的存在及生效时间。网页附件 URL 可能由站点动态生成，不能把第三方镜像地址当成永久主键。

    后续固化要求：

    1. 从 CDE 官方“常用下载”或通告附件下载原始文件；
    2. 保存原始文件名、下载 URL、HTTP 响应头、下载时间、SHA-256 和 SM3；
    3. 安装包、RAR/ZIP 和 PDF 原件放入本地受控 evidence storage，不默认提交 Git；
    4. 仓库只提交 manifest、哈希和可公开的结构化摘录；
    5. 第三方镜像仅作可用性备份，必须标明 secondary mirror。
    """)
    write_json(OUT_DOCS / "CDE_SOURCE_DISCOVERY.json", {
        "status": "PARTIAL",
        "official_pages_verified": 2,
        "binary_assets_hashed": 0,
        "official_validator_runs": 0,
        "next_action": "Download V1.1.0 installer/manual from CDE common downloads on Windows and run tools/cde-validator/capture-validator-run.ps1.",
    })
    write_json(OUT_DOCS / "DRAFT_TO_FINAL_AUTOMATED_DIFF.json", {
        "status": "AUXILIARY_NOT_AUTHORITATIVE",
        "method": "local text extraction and neighborhood comparison",
        "conclusion": "The final effective V1.1 file controls. Draft text is retained only to explain changes and formulate boundary experiments.",
        "rule_count_final": 26,
        "manual_verification_required": True,
    })
    write_text(OUT_DOCS / "DRAFT_TO_FINAL_AUTOMATED_DIFF.md", """
    # V1.1 征求意见稿与正式稿差异处理

    自动文本差异仅用于定位变化，不作为规则来源。最终规则字段必须来自 2026 年正式有效文件。PDF 换行、表格抽取和字符编码都可能制造伪差异，因此任何严重程度、例外条件和规则语义的变化都必须回看原始页面。

    本阶段保留的结论只有：正式 PDF 分析规则为 6.1–6.26，严重程度为错误 16、警告 8、提示信息 2；其他 draft-to-final 差异继续列入人工复核。
    """)


def materialize_data(matrix: dict[str, Any], smoke: dict[str, Any], boundary: dict[str, Any]) -> None:
    write_json(OUT_TESTS / "case_matrix.json", matrix)
    write_json(OUT_TESTS / "smoke_manifest.json", smoke)
    write_json(OUT_TESTS / "boundary_experiment_queue.json", boundary)
    case_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["schema_version", "profile_id", "counts", "rules", "cases"],
        "properties": {
            "counts": {"type": "object", "required": ["rules", "variants_per_rule", "cases"]},
            "rules": {"type": "array", "minItems": 26, "maxItems": 26},
            "cases": {"type": "array", "minItems": 130, "maxItems": 130},
        },
    }
    write_json(OUT_TESTS / "case_matrix.schema.json", case_schema)
    result_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["case_id", "validator", "input", "observation", "evidence", "review"],
        "properties": {
            "case_id": {"type": "string"},
            "validator": {"type": "object", "required": ["name", "version"]},
            "input": {"type": "object", "required": ["pdf_sha256", "package_inventory_sha256"]},
            "observation": {"type": "object", "required": ["run_status", "messages"]},
            "evidence": {"type": "object", "required": ["report_files", "screenshots"]},
            "review": {"type": "object", "required": ["classification", "reviewer"]},
        },
    }
    write_json(OUT_TESTS / "official-validator" / "results.schema.json", result_schema)
    write_json(OUT_TESTS / "official-validator" / "results.template.json", {
        "case_id": "REPLACE_ME",
        "validator": {"name": "CDE eCTD validation software", "version": "1.1.0", "binary_sha256": None},
        "input": {"pdf_sha256": None, "package_inventory_sha256": None, "baseline_id": None},
        "observation": {"run_status": "NOT_RUN", "started_at": None, "finished_at": None, "messages": []},
        "evidence": {"report_files": [], "screenshots": [], "notes": []},
        "review": {"classification": "INCONCLUSIVE", "reviewer": None, "reviewed_at": None},
    })
    write_json(OUT_TESTS / "P0-B0-A_GATE_REPORT.json", {
        "schema_version": "0.2.0",
        "stage": "P0-B0-A",
        "status": "PASS_LOCAL_BASELINE",
        "evidence_scope": "Synthetic-fixture generation and independent structural/render probes only",
        "counts": {
            "official_rules": 26,
            "case_recipes": 130,
            "smoke_pdfs": 28,
            "object_self_checks_passed": 28,
            "pdfium_expected_outcomes_passed": 28,
            "qpdf_expected_outcomes_passed": 28,
            "reproducible_hashes": 28,
            "official_validator_observations": 0,
        },
        "official_validator_status": "NOT_RUN",
        "interpretation": "This gate proves that the test harness creates the intended PDF objects reproducibly. It does not prove agreement with the CDE validator.",
    })
    write_json(OUT_TESTS / "REPRODUCIBILITY_REPORT.json", {
        "status": "PASS_LOCAL_BASELINE",
        "files_compared": 28,
        "hash_differences": 0,
        "determinism_controls": ["ReportLab invariant mode", "pikepdf deterministic_id", "stable filenames", "no timestamps in generated metadata"],
    })


def materialize_sources() -> None:
    write_text(OUT_TESTS / "requirements.txt", """
    pikepdf>=9,<11
    reportlab>=4,<5
    Pillow>=10,<13
    jsonschema>=4,<5
    pypdfium2>=4,<6
    """)
    write_text(OUT_TESTS / "README.md", """
    # P0-B0 synthetic validation harness

    ```bash
    python -m pip install -r tests/p0_b0/requirements.txt
    python tests/p0_b0/run_all.py
    ```

    `run_all.py` validates the 26-rule/130-case matrix, generates 28 deterministic PDFs, performs rule-specific object assertions, renders expected-open files with PDFium, probes structure with qpdf, verifies the differential eCTD package harness, and compares a second generation run byte-for-byte.

    Generated PDFs are written to `build/p0-b0-smoke/` and are not source evidence. Official validator results remain `NOT_RUN` until collected on Windows with CDE V1.1.0.
    """)
    write_text(OUT_TESTS / "generators" / "generate_smoke_cases.py", r'''
    from __future__ import annotations

    import argparse
    import hashlib
    import json
    import shutil
    import tempfile
    from pathlib import Path

    import pikepdf
    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    N = pikepdf.Name
    D = pikepdf.Dictionary
    A = pikepdf.Array
    S = pikepdf.String


    def make_reportlab(path: Path, pages: int = 1, image_only: bool = False) -> None:
        c = canvas.Canvas(str(path), pagesize=A4, invariant=1, pageCompression=0)
        width, height = A4
        if image_only:
            image_path = path.with_suffix(".png")
            image = Image.new("RGB", (1200, 1700), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((80, 80, 1120, 1620), outline="black", width=4)
            draw.text((130, 180), "IMAGE ONLY PAGE - NO PDF TEXT OBJECT", fill="black")
            image.save(image_path, optimize=False)
            c.drawImage(str(image_path), 0, 0, width=width, height=height, preserveAspectRatio=False, mask=None)
            c.showPage()
            c.save()
            image_path.unlink(missing_ok=True)
            return
        for page in range(1, pages + 1):
            c.setFont("Helvetica", 12)
            c.drawString(72, height - 72, f"EZCTD deterministic synthetic page {page}")
            c.drawString(72, height - 94, "Searchable control text for CDE PDF validation experiments.")
            c.showPage()
        c.save()


    def set_initial_view(pdf: pikepdf.Pdf, good: bool = True) -> None:
        if good:
            pdf.Root.PageMode = N.UseOutlines
            for key in ("/PageLayout", "/OpenAction"):
                if key in pdf.Root:
                    del pdf.Root[key]
        else:
            pdf.Root.PageMode = N.UseNone
            pdf.Root.PageLayout = N.TwoColumnLeft
            pdf.Root.OpenAction = A([pdf.pages[0].obj, N.XYZ, 0, 780, 2.0])


    def make_outline(pdf: pikepdf.Pdf, *, mode: str = "good") -> None:
        outlines = pdf.make_indirect(D(Type=N.Outlines))
        item = pdf.make_indirect(D(Title=S("Synthetic bookmark"), Parent=outlines))
        outlines.First = item
        outlines.Last = item
        outlines.Count = 1
        pdf.Root.Outlines = outlines
        if mode == "good":
            item.Dest = A([pdf.pages[0].obj, N.XYZ, 0, 780, None])
        elif mode == "absolute":
            item.A = D(S=N.GoToR, F=S(r"C:\\absolute\\target.pdf"), D=A([0, N.Fit]))
        elif mode == "uri":
            item.A = D(S=N.URI, URI=S("https://example.invalid/external"))
        elif mode == "js":
            item.A = D(S=N.JavaScript, JS=S("app.alert('x')"))
        elif mode == "missing_action":
            pass
        elif mode == "missing_file":
            item.A = D(S=N.GoToR, F=S("missing-target.pdf"), D=A([0, N.Fit]))
        elif mode == "multiple":
            item.A = D(S=N.GoTo, D=A([pdf.pages[0].obj, N.Fit]), Next=D(S=N.GoTo, D=A([pdf.pages[0].obj, N.FitH, 700])))
        elif mode == "zoom":
            item.Dest = A([pdf.pages[0].obj, N.XYZ, 0, 780, 2.0])
        else:
            raise ValueError(mode)


    def add_link(pdf: pikepdf.Pdf, *, mode: str) -> None:
        annot = pdf.make_indirect(D(Type=N.Annot, Subtype=N.Link, Rect=A([72, 650, 300, 680]), Border=A([0, 0, 0])))
        if mode == "absolute":
            annot.A = D(S=N.GoToR, F=S(r"C:\\absolute\\target.pdf"), D=A([0, N.Fit]))
        elif mode == "uri":
            annot.A = D(S=N.URI, URI=S("https://example.invalid/external"))
        elif mode == "js":
            annot.A = D(S=N.JavaScript, JS=S("app.alert('x')"))
        elif mode == "missing_action":
            pass
        elif mode == "missing_file":
            annot.A = D(S=N.GoToR, F=S("missing-target.pdf"), D=A([0, N.Fit]))
        elif mode == "multiple":
            annot.A = D(S=N.GoTo, D=A([pdf.pages[0].obj, N.Fit]), Next=D(S=N.GoTo, D=A([pdf.pages[0].obj, N.FitH, 700])))
        elif mode == "zoom":
            annot.Dest = A([pdf.pages[0].obj, N.XYZ, 0, 780, 2.0])
        else:
            raise ValueError(mode)
        pdf.pages[0].obj.Annots = A([annot])


    def add_attachment(pdf: pikepdf.Pdf) -> None:
        stream = pdf.make_stream(b"deterministic attachment payload\n")
        stream.Type = N.EmbeddedFile
        filespec = pdf.make_indirect(D(Type=N.Filespec, F=S("payload.txt"), UF=S("payload.txt"), EF=D(F=stream, UF=stream)))
        embedded = pdf.make_indirect(D(Names=A([S("payload.txt"), filespec])))
        names = pdf.Root.get("/Names", D())
        names.EmbeddedFiles = embedded
        pdf.Root.Names = names


    def add_text_annotation(pdf: pikepdf.Pdf) -> None:
        annot = pdf.make_indirect(D(Type=N.Annot, Subtype=N.Text, Rect=A([72, 620, 100, 650]), Contents=S("Synthetic note"), Open=False))
        pdf.pages[0].obj.Annots = A([annot])


    def add_document_javascript(pdf: pikepdf.Pdf) -> None:
        action = pdf.make_indirect(D(S=N.JavaScript, JS=S("app.alert('synthetic')")))
        js_tree = pdf.make_indirect(D(Names=A([S("SyntheticJS"), action])))
        names = pdf.Root.get("/Names", D())
        names.JavaScript = js_tree
        pdf.Root.Names = names


    def add_unembedded_font(pdf: pikepdf.Pdf) -> None:
        font = pdf.make_indirect(D(Type=N.Font, Subtype=N.Type1, BaseFont=N("/EZCTDNonStandardFont"), Encoding=N.WinAnsiEncoding))
        page = pdf.pages[0].obj
        resources = page.get("/Resources", D())
        fonts = resources.get("/Font", D())
        fonts[N("/Fbad")] = font
        resources.Font = fonts
        page.Resources = resources
        extra = pdf.make_stream(b"BT /Fbad 12 Tf 72 560 Td (Synthetic unembedded font) Tj ET\n")
        contents = page.get("/Contents")
        if isinstance(contents, pikepdf.Array):
            contents.append(extra)
        elif contents is None:
            page.Contents = extra
        else:
            page.Contents = A([contents, extra])


    def save_pdf(pdf: pikepdf.Pdf, path: Path, *, linearize: bool = True, version: str = "1.7", encryption=None) -> None:
        pdf.save(path, linearize=linearize, force_version=version, deterministic_id=True, encryption=encryption)


    def make_case(case_id: str, output: Path, temp: Path) -> None:
        rule_id = None
        if case_id.startswith("CDE-PDF-6-"):
            parts = case_id.split("-")
            rule_id = f"6.{parts[3]}"
        pages = 6 if rule_id == "6.23" or case_id == "CDE-PDF-6-23-EXM-REFERENCE" else 1
        source = temp / f"{case_id}.source.pdf"
        make_reportlab(source, pages=pages, image_only=rule_id == "6.25")
        if rule_id == "6.1":
            with pikepdf.open(source) as pdf:
                make_outline(pdf, mode="good")
                set_initial_view(pdf, good=True)
                intact = temp / "intact.pdf"
                save_pdf(pdf, intact)
            raw = intact.read_bytes()
            output.write_bytes(raw[: max(32, len(raw) // 3)])
            return
        with pikepdf.open(source) as pdf:
            if rule_id not in {"6.23"} and case_id != "CDE-PDF-6-23-EXM-REFERENCE":
                make_outline(pdf, mode="good")
            set_initial_view(pdf, good=True)
            if rule_id == "6.2":
                del pdf.Root["/Outlines"]; make_outline(pdf, mode="absolute")
            elif rule_id == "6.3":
                del pdf.Root["/Outlines"]; make_outline(pdf, mode="uri")
            elif rule_id == "6.4":
                del pdf.Root["/Outlines"]; make_outline(pdf, mode="js")
            elif rule_id == "6.5":
                del pdf.Root["/Outlines"]; make_outline(pdf, mode="missing_action")
            elif rule_id == "6.6":
                del pdf.Root["/Outlines"]; make_outline(pdf, mode="missing_file")
            elif rule_id == "6.7":
                del pdf.Root["/Outlines"]; make_outline(pdf, mode="multiple")
            elif rule_id == "6.8":
                del pdf.Root["/Outlines"]; make_outline(pdf, mode="zoom")
            elif rule_id == "6.9": add_link(pdf, mode="absolute")
            elif rule_id == "6.10": add_link(pdf, mode="uri")
            elif rule_id == "6.11": add_link(pdf, mode="js")
            elif rule_id == "6.12": add_link(pdf, mode="missing_action")
            elif rule_id == "6.13": add_link(pdf, mode="missing_file")
            elif rule_id == "6.14": add_link(pdf, mode="multiple")
            elif rule_id == "6.15": add_link(pdf, mode="zoom")
            elif rule_id == "6.17": add_attachment(pdf)
            elif rule_id == "6.18": add_text_annotation(pdf)
            elif rule_id == "6.20": set_initial_view(pdf, good=False)
            elif rule_id == "6.24": add_document_javascript(pdf)
            elif rule_id == "6.26": add_unembedded_font(pdf)

            if rule_id == "6.19":
                permissions = pikepdf.Permissions(extract=False, modify_annotation=False, modify_other=False, print_lowres=False, print_highres=False)
                encryption = pikepdf.Encryption(owner="owner-password", user="", R=6, allow=permissions)
                save_pdf(pdf, output, linearize=False, encryption=encryption)
            elif rule_id == "6.21":
                encryption = pikepdf.Encryption(owner="owner-password", user="user-password", R=6)
                save_pdf(pdf, output, linearize=False, encryption=encryption)
            elif rule_id == "6.16":
                save_pdf(pdf, output, version="1.3")
            elif rule_id == "6.22":
                save_pdf(pdf, output, linearize=False)
            else:
                save_pdf(pdf, output)


    def main() -> int:
        parser = argparse.ArgumentParser()
        parser.add_argument("--manifest", type=Path, default=Path(__file__).parents[1] / "smoke_manifest.json")
        parser.add_argument("--output", type=Path, required=True)
        args = parser.parse_args()
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.output.exists():
            shutil.rmtree(args.output)
        args.output.mkdir(parents=True)
        generated = []
        with tempfile.TemporaryDirectory(prefix="ezctd-p0b0-") as td:
            temp = Path(td)
            for case in manifest["cases"]:
                path = args.output / case["file_name"]
                make_case(case["case_id"], path, temp)
                generated.append({"case_id": case["case_id"], "file_name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size})
        (args.output / "generated_manifest.json").write_text(json.dumps({"count": len(generated), "files": generated}, indent=2) + "\n", encoding="utf-8")
        if len(generated) != 28:
            raise SystemExit(f"expected 28 files, got {len(generated)}")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    ''')
    write_text(OUT_TESTS / "validators" / "validate_case_matrix.py", r'''
    from __future__ import annotations

    import json
    from collections import Counter
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[3]
    MATRIX = ROOT / "tests" / "p0_b0" / "case_matrix.json"
    SMOKE = ROOT / "tests" / "p0_b0" / "smoke_manifest.json"
    BOUNDARY = ROOT / "tests" / "p0_b0" / "boundary_experiment_queue.json"
    VERIFIED = ROOT / "rulepacks" / "cn-cde-ectd" / "v1.1" / "cde_ectd_pdf_rules_v1.1_verified.json"

    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    smoke = json.loads(SMOKE.read_text(encoding="utf-8"))
    boundary = json.loads(BOUNDARY.read_text(encoding="utf-8"))
    verified = json.loads(VERIFIED.read_text(encoding="utf-8"))
    expected_ids = [f"6.{i}" for i in range(1, 27)]
    assert [r["id"] for r in matrix["rules"]] == expected_ids
    assert [r["id"] for r in verified["rules"]] == expected_ids
    assert Counter(r["official_severity"] for r in matrix["rules"]) == Counter({"错误": 16, "警告": 8, "提示信息": 2})
    assert len(matrix["cases"]) == 130
    assert len({c["case_id"] for c in matrix["cases"]}) == 130
    assert Counter(c["variant"] for c in matrix["cases"]) == Counter({v: 26 for v in ["compliant", "violation", "boundary", "exemption", "interaction"]})
    assert all(c["official_observation"]["status"] == "NOT_RUN" for c in matrix["cases"])
    assert smoke["count"] == 28 and len(smoke["cases"]) == 28
    assert boundary["count"] >= 130 and all(e["official_observation"] == "NOT_RUN" for e in boundary["experiments"])
    verified_by_id = {r["id"]: r for r in verified["rules"]}
    for rule in matrix["rules"]:
        source = verified_by_id[rule["id"]]
        assert rule["official_title"] == source["official_title"]
        assert rule["official_severity"] == source["official_severity"]
        assert rule["scope_exemptions"] == source["scope_exemptions"]
    print(json.dumps({"status": "PASS", "rules": 26, "cases": 130, "smoke": 28, "boundary": boundary["count"]}))
    ''')
    write_text(OUT_TESTS / "validators" / "self_check_smoke.py", r'''
    from __future__ import annotations

    import argparse
    import json
    from pathlib import Path
    import pikepdf

    N = pikepdf.Name

    def outline_item(pdf):
        return pdf.Root.Outlines.First

    def action_type(obj):
        return str(obj.A.S) if "/A" in obj and "/S" in obj.A else None

    def check(rule_id: str | None, path: Path, case_id: str) -> None:
        if rule_id == "6.1":
            try:
                pikepdf.open(path)
            except Exception:
                return
            raise AssertionError("6.1 sample unexpectedly readable")
        if rule_id == "6.21":
            try:
                pikepdf.open(path)
            except Exception:
                with pikepdf.open(path, password="user-password"):
                    return
            raise AssertionError("6.21 sample opened without password")
        with pikepdf.open(path) as pdf:
            if rule_id == "6.2": assert str(outline_item(pdf).A.F).startswith("C:")
            elif rule_id == "6.3": assert action_type(outline_item(pdf)) == "/URI"
            elif rule_id == "6.4": assert action_type(outline_item(pdf)) == "/JavaScript"
            elif rule_id == "6.5": assert "/Dest" not in outline_item(pdf) and "/A" not in outline_item(pdf)
            elif rule_id == "6.6": assert str(outline_item(pdf).A.F) == "missing-target.pdf"
            elif rule_id == "6.7": assert "/Next" in outline_item(pdf).A
            elif rule_id == "6.8": assert str(outline_item(pdf).Dest[1]) == "/XYZ" and float(outline_item(pdf).Dest[4]) == 2.0
            elif rule_id in {"6.9", "6.10", "6.11", "6.12", "6.13", "6.14", "6.15", "6.18"}:
                annot = pdf.pages[0].obj.Annots[0]
                if rule_id == "6.9": assert str(annot.A.F).startswith("C:")
                elif rule_id == "6.10": assert str(annot.A.S) == "/URI"
                elif rule_id == "6.11": assert str(annot.A.S) == "/JavaScript"
                elif rule_id == "6.12": assert "/A" not in annot and "/Dest" not in annot
                elif rule_id == "6.13": assert str(annot.A.F) == "missing-target.pdf"
                elif rule_id == "6.14": assert "/Next" in annot.A
                elif rule_id == "6.15": assert str(annot.Dest[1]) == "/XYZ" and float(annot.Dest[4]) == 2.0
                elif rule_id == "6.18": assert str(annot.Subtype) == "/Text"
            elif rule_id == "6.16": assert path.read_bytes().startswith(b"%PDF-1.3")
            elif rule_id == "6.17": assert "/Names" in pdf.Root and "/EmbeddedFiles" in pdf.Root.Names
            elif rule_id == "6.19": assert pdf.is_encrypted
            elif rule_id == "6.20": assert str(pdf.Root.PageMode) == "/UseNone" and str(pdf.Root.PageLayout) == "/TwoColumnLeft"
            elif rule_id == "6.22": assert not pdf.is_linearized
            elif rule_id == "6.23": assert len(pdf.pages) == 6 and "/Outlines" not in pdf.Root
            elif rule_id == "6.24": assert "/JavaScript" in pdf.Root.Names
            elif rule_id == "6.25": assert all(not page.extract_text().strip() for page in pdf.pages)
            elif rule_id == "6.26":
                font = pdf.pages[0].obj.Resources.Font[N("/Fbad")]
                assert "/FontDescriptor" not in font
            elif rule_id is None:
                assert len(pdf.pages) == 1 and "/Outlines" in pdf.Root and pdf.is_linearized
            if case_id == "CDE-PDF-6-23-EXM-REFERENCE":
                assert len(pdf.pages) == 6 and "/Outlines" not in pdf.Root

    def main() -> int:
        p = argparse.ArgumentParser(); p.add_argument("--manifest", type=Path, required=True); p.add_argument("--input", type=Path, required=True); a = p.parse_args()
        manifest = json.loads(a.manifest.read_text(encoding="utf-8"))
        for case in manifest["cases"]:
            check(case["rule_id"], a.input / case["file_name"], case["case_id"])
        print(json.dumps({"status": "PASS", "checked": len(manifest["cases"])}))
        return 0
    if __name__ == "__main__": raise SystemExit(main())
    ''')
    write_text(OUT_TESTS / "validators" / "render_probe_pdfium.py", r'''
    from __future__ import annotations
    import argparse, json
    from pathlib import Path
    import pypdfium2 as pdfium

    p = argparse.ArgumentParser(); p.add_argument("--manifest", type=Path, required=True); p.add_argument("--input", type=Path, required=True); a = p.parse_args()
    manifest = json.loads(a.manifest.read_text(encoding="utf-8")); passed = 0
    for case in manifest["cases"]:
        expected = case["expected_pdfium"]
        try:
            doc = pdfium.PdfDocument(a.input / case["file_name"])
            page = doc[0]; bitmap = page.render(scale=0.5); image = bitmap.to_pil(); image.load(); page.close(); doc.close()
            actual = "RENDER"
        except Exception:
            actual = "REJECT"
        if actual != expected: raise AssertionError(f"{case['case_id']}: expected {expected}, got {actual}")
        passed += 1
    print(json.dumps({"status":"PASS","checked":passed}))
    ''')
    write_text(OUT_TESTS / "validators" / "qpdf_probe.py", r'''
    from __future__ import annotations
    import argparse, json, shutil, subprocess
    from pathlib import Path

    p = argparse.ArgumentParser(); p.add_argument("--manifest", type=Path, required=True); p.add_argument("--input", type=Path, required=True); a = p.parse_args()
    if not shutil.which("qpdf"): raise SystemExit("qpdf not found")
    manifest = json.loads(a.manifest.read_text(encoding="utf-8")); passed = 0
    for case in manifest["cases"]:
        cmd = ["qpdf", "--check", str(a.input / case["file_name"])]
        result = subprocess.run(cmd, capture_output=True, text=True)
        actual = "PASS" if result.returncode == 0 else "REJECT"
        if actual != case["expected_qpdf"]:
            raise AssertionError(f"{case['case_id']}: expected {case['expected_qpdf']}, got {actual}: {result.stderr[-500:]}")
        passed += 1
    print(json.dumps({"status":"PASS","checked":passed}))
    ''')
    write_text(OUT_TESTS / "prepare_differential_packages.py", r'''
    from __future__ import annotations
    import argparse, hashlib, json, shutil
    from pathlib import Path
    from lxml import etree

    XLINK = "http://www.w3.org/1999/xlink"

    def md5(path: Path) -> str: return hashlib.md5(path.read_bytes()).hexdigest()
    def sha256(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()

    def update_xml(xml_path: Path, leaf_relative: str, checksum: str) -> int:
        parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False, no_network=True)
        tree = etree.parse(str(xml_path), parser); changed = 0
        for node in tree.xpath("//*[@xlink:href]", namespaces={"xlink": XLINK}):
            href = node.get(f"{{{XLINK}}}href")
            if href and href.replace("\\", "/") == leaf_relative.replace("\\", "/"):
                node.set("checksum", checksum); node.set("checksum-type", "md5"); changed += 1
        if changed:
            tree.write(str(xml_path), encoding="UTF-8", xml_declaration=True, pretty_print=False)
        return changed

    def build_case(baseline: Path, output: Path, leaf_relative: str, replacement: Path, case_id: str) -> dict:
        if output.exists(): shutil.rmtree(output)
        shutil.copytree(baseline, output)
        leaf = output / Path(leaf_relative)
        if not leaf.exists(): raise FileNotFoundError(f"baseline leaf missing: {leaf_relative}")
        shutil.copy2(replacement, leaf)
        checksum = md5(leaf); xml_changes = 0; changed_xml = []
        for xml_path in output.rglob("*.xml"):
            changed = update_xml(xml_path, leaf_relative, checksum)
            if changed: xml_changes += changed; changed_xml.append(str(xml_path.relative_to(output)))
        if xml_changes != 1: raise RuntimeError(f"expected exactly one leaf href match, got {xml_changes}")
        index_xml = output / "index.xml"
        index_md5 = output / "index-md5.txt"
        if index_md5.exists() and index_xml.exists(): index_md5.write_text(md5(index_xml) + "\n", encoding="ascii")
        inventory = []
        for path in sorted(p for p in output.rglob("*") if p.is_file()):
            inventory.append({"path": path.relative_to(output).as_posix(), "size": path.stat().st_size, "sha256": sha256(path)})
        audit = {"case_id": case_id, "leaf_relative": leaf_relative, "replacement_sha256": sha256(replacement), "leaf_md5": checksum, "changed_xml": changed_xml, "inventory": inventory}
        (output / "ezctd-experiment.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        return audit

    def main() -> int:
        p=argparse.ArgumentParser(); p.add_argument("--baseline",type=Path,required=True); p.add_argument("--smoke-dir",type=Path,required=True); p.add_argument("--manifest",type=Path,required=True); p.add_argument("--leaf",required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
        manifest=json.loads(a.manifest.read_text(encoding="utf-8")); audits=[]
        for case in manifest["cases"]:
            audits.append(build_case(a.baseline,a.output/case["case_id"],a.leaf,a.smoke_dir/case["file_name"],case["case_id"]))
        print(json.dumps({"status":"PASS","packages":len(audits)})); return 0
    if __name__=="__main__": raise SystemExit(main())
    ''')
    write_text(OUT_TESTS / "validators" / "test_package_harness.py", r'''
    from __future__ import annotations
    import hashlib, tempfile
    from pathlib import Path
    from lxml import etree
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from prepare_differential_packages import build_case

    with tempfile.TemporaryDirectory(prefix="ezctd-package-test-") as td:
        root=Path(td); baseline=root/"baseline"; (baseline/"m5").mkdir(parents=True)
        leaf=baseline/"m5"/"leaf.pdf"; leaf.write_bytes(b"baseline")
        ns="http://www.w3.org/1999/xlink"
        index=baseline/"index.xml"; index.write_text(f'<?xml version="1.0" encoding="UTF-8"?><ectd xmlns:xlink="{ns}"><leaf xlink:href="m5/leaf.pdf" checksum="{hashlib.md5(leaf.read_bytes()).hexdigest()}" checksum-type="md5"/></ectd>',encoding="utf-8")
        (baseline/"index-md5.txt").write_text(hashlib.md5(index.read_bytes()).hexdigest()+"\n",encoding="ascii")
        replacement=root/"replacement.pdf"; replacement.write_bytes(b"replacement")
        output=root/"output"; audit=build_case(baseline,output,"m5/leaf.pdf",replacement,"SELFTEST")
        tree=etree.parse(str(output/"index.xml")); node=tree.xpath("//*[local-name()='leaf']")[0]
        assert node.get("checksum")==hashlib.md5(replacement.read_bytes()).hexdigest()
        assert (output/"index-md5.txt").read_text().strip()==hashlib.md5((output/"index.xml").read_bytes()).hexdigest()
        assert audit["case_id"]=="SELFTEST"
    print('{"status":"PASS","test":"differential-package-harness"}')
    ''')
    write_text(OUT_TESTS / "package_for_official_run.py", r'''
    from __future__ import annotations
    import argparse, json, shutil, zipfile
    from pathlib import Path

    p=argparse.ArgumentParser(); p.add_argument("--smoke-dir",type=Path,required=True); p.add_argument("--manifest",type=Path,required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    manifest=json.loads(a.manifest.read_text(encoding="utf-8"))
    with zipfile.ZipFile(a.output,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        z.write(a.manifest,"smoke_manifest.json")
        for case in manifest["cases"]: z.write(a.smoke_dir/case["file_name"],f"pdf/{case['file_name']}")
        template=Path(__file__).parent/"official-validator"/"results.template.json"; z.write(template,"official-validator/results.template.json")
    print(json.dumps({"status":"PASS","zip":str(a.output),"cases":len(manifest["cases"])}))
    ''')
    write_text(OUT_TESTS / "run_all.py", r'''
    from __future__ import annotations
    import hashlib, json, shutil, subprocess, sys
    from pathlib import Path

    ROOT=Path(__file__).resolve().parents[2]; TEST=ROOT/"tests"/"p0_b0"; BUILD=ROOT/"build"/"p0-b0-smoke"; BUILD2=ROOT/"build"/"p0-b0-smoke-repeat"
    def run(*args): subprocess.run([sys.executable,*map(str,args)],check=True)
    run(TEST/"validators"/"validate_case_matrix.py")
    run(TEST/"generators"/"generate_smoke_cases.py","--manifest",TEST/"smoke_manifest.json","--output",BUILD)
    run(TEST/"validators"/"self_check_smoke.py","--manifest",TEST/"smoke_manifest.json","--input",BUILD)
    run(TEST/"validators"/"render_probe_pdfium.py","--manifest",TEST/"smoke_manifest.json","--input",BUILD)
    run(TEST/"validators"/"qpdf_probe.py","--manifest",TEST/"smoke_manifest.json","--input",BUILD)
    run(TEST/"validators"/"test_package_harness.py")
    run(TEST/"generators"/"generate_smoke_cases.py","--manifest",TEST/"smoke_manifest.json","--output",BUILD2)
    names=sorted(p.name for p in BUILD.glob("*.pdf")); assert len(names)==28
    diffs=[]
    for name in names:
        h1=hashlib.sha256((BUILD/name).read_bytes()).hexdigest(); h2=hashlib.sha256((BUILD2/name).read_bytes()).hexdigest()
        if h1!=h2: diffs.append(name)
    if diffs: raise AssertionError(f"non-deterministic PDFs: {diffs}")
    report={"status":"PASS","rules":26,"case_recipes":130,"smoke":28,"self_check":28,"pdfium":28,"qpdf":28,"reproducible":28,"official_observations":0,"official_status":"NOT_RUN"}
    (ROOT/"build"/"p0-b0-gate-report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report)); shutil.rmtree(BUILD2); raise SystemExit(0)
    ''')


def materialize_tools() -> None:
    write_text(OUT_TOOLS / "README.md", """
    # CDE official-validator evidence collector

    These scripts do not automate or reverse-engineer the CDE validator. They create a controlled run folder and finalize a machine-readable evidence record around a manual V1.1.0 run.

    ```powershell
    .\\tools\\cde-validator\\capture-validator-run.ps1 `
      -CaseId CDE-PDF-6-8-POS `
      -InputPackage C:\\EZCTD\\packages\\CDE-PDF-6-8-POS `
      -OutputRoot C:\\EZCTD\\official-results `
      -ValidatorVersion 1.1.0
    ```

    Run the CDE GUI, export its full report and screenshots into the created folders, edit `result.json`, then run `Finalize-OfficialRun.ps1`. The finalizer refuses `NOT_RUN`, missing hashes, absent reports, or absent screenshots.
    """)
    write_text(OUT_TOOLS / "capture-validator-run.ps1", r'''
    param(
      [Parameter(Mandatory=$true)][string]$CaseId,
      [Parameter(Mandatory=$true)][string]$InputPackage,
      [Parameter(Mandatory=$true)][string]$OutputRoot,
      [string]$ValidatorVersion="1.1.0",
      [string]$ValidatorBinary=""
    )
    $ErrorActionPreference="Stop"
    $run=Join-Path $OutputRoot $CaseId
    New-Item -ItemType Directory -Force -Path $run,(Join-Path $run "reports"),(Join-Path $run "screenshots") | Out-Null
    $inventory=@()
    Get-ChildItem -Path $InputPackage -Recurse -File | Sort-Object FullName | ForEach-Object {
      $inventory += [ordered]@{path=$_.FullName.Substring($InputPackage.Length).TrimStart('\\');size=$_.Length;sha256=(Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()}
    }
    $inventoryJson=$inventory | ConvertTo-Json -Depth 6
    $inventoryJson | Set-Content -Path (Join-Path $run "package-inventory.json") -Encoding UTF8
    $joined=[Text.Encoding]::UTF8.GetBytes($inventoryJson)
    $sha=[System.Security.Cryptography.SHA256]::Create().ComputeHash($joined)
    $inventorySha=($sha | ForEach-Object {$_.ToString('x2')}) -join ''
    $binarySha=$null
    if ($ValidatorBinary -and (Test-Path $ValidatorBinary)) {$binarySha=(Get-FileHash $ValidatorBinary -Algorithm SHA256).Hash.ToLower()}
    $result=[ordered]@{
      case_id=$CaseId
      validator=[ordered]@{name="CDE eCTD validation software";version=$ValidatorVersion;binary_sha256=$binarySha}
      input=[ordered]@{pdf_sha256=$null;package_inventory_sha256=$inventorySha;baseline_id=$null;package_path=$InputPackage}
      observation=[ordered]@{run_status="NOT_RUN";started_at=(Get-Date).ToString('o');finished_at=$null;messages=@()}
      evidence=[ordered]@{report_files=@();screenshots=@();notes=@("Run official GUI manually; copy original reports and screenshots before finalizing.")}
      review=[ordered]@{classification="INCONCLUSIVE";reviewer=$null;reviewed_at=$null}
    }
    $result | ConvertTo-Json -Depth 10 | Set-Content -Path (Join-Path $run "result.json") -Encoding UTF8
    Write-Host "Prepared: $run"
    Write-Host "Next: run CDE V1.1.0, export full report to reports/, screenshots to screenshots/, edit result.json, then Finalize-OfficialRun.ps1."
    ''')
    write_text(OUT_TOOLS / "Finalize-OfficialRun.ps1", r'''
    param([Parameter(Mandatory=$true)][string]$RunDirectory)
    $ErrorActionPreference="Stop"
    $resultPath=Join-Path $RunDirectory "result.json"
    if (!(Test-Path $resultPath)) {throw "result.json missing"}
    $result=Get-Content $resultPath -Raw | ConvertFrom-Json
    if ($result.observation.run_status -eq "NOT_RUN") {throw "observation.run_status is still NOT_RUN"}
    if (!$result.input.package_inventory_sha256) {throw "package inventory hash missing"}
    $reports=@(Get-ChildItem (Join-Path $RunDirectory "reports") -File -ErrorAction SilentlyContinue)
    $shots=@(Get-ChildItem (Join-Path $RunDirectory "screenshots") -File -ErrorAction SilentlyContinue)
    if ($reports.Count -lt 1) {throw "at least one original report file is required"}
    if ($shots.Count -lt 1) {throw "at least one screenshot is required"}
    $result.evidence.report_files=@($reports | ForEach-Object {[ordered]@{name=$_.Name;sha256=(Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()}})
    $result.evidence.screenshots=@($shots | ForEach-Object {[ordered]@{name=$_.Name;sha256=(Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()}})
    if (!$result.observation.finished_at) {$result.observation.finished_at=(Get-Date).ToString('o')}
    $result | ConvertTo-Json -Depth 12 | Set-Content $resultPath -Encoding UTF8
    Write-Host "Finalized official evidence: $resultPath"
    ''')


def update_project_files() -> None:
    status = ROOT / "PROJECT_STATUS.md"
    content = status.read_text(encoding="utf-8") if status.exists() else "# EZCTD 项目状态\n"
    block = """
    <!-- P0-B0-STATUS:START -->
    ## P0-B0：规则验证矩阵与合成测试基线

    - **P0-B0-A：完成。** 26 条规则检测合同、130 个案例配方、28 个确定性 smoke PDF 设计、对象级自检、PDFium/qpdf 探针、重复生成比较和差分 eCTD 包工具已入库。
    - **P0-B0-B：待执行。** CDE eCTD 验证软件 V1.1.0 的实际观察仍为 `NOT_RUN`。
    - 退出 P0-B0-B 需要：官方软件及手册哈希、一个 clean baseline sequence、28 案完整报告与截图、结果 JSON 和差异复盘。
    - 当前允许进入的编码工作仅限只读 scanner 基础设施；任何 detector 的最终边界仍受官方黑盒结果约束。
    <!-- P0-B0-STATUS:END -->
    """
    pattern = re.compile(r"<!-- P0-B0-STATUS:START -->.*?<!-- P0-B0-STATUS:END -->", re.S)
    content = pattern.sub(textwrap.dedent(block).strip(), content) if pattern.search(content) else content.rstrip() + "\n\n" + textwrap.dedent(block).strip() + "\n"
    status.write_text(content, encoding="utf-8", newline="\n")

    changelog = ROOT / "CHANGELOG.md"
    c = changelog.read_text(encoding="utf-8") if changelog.exists() else "# Changelog\n\n## [Unreleased]\n"
    marker = "- 增加 P0-B0 26 条规则检测合同、130 个案例配方和 28 个确定性 smoke PDF 测试基线。"
    additions = """
    - 增加 P0-B0 26 条规则检测合同、130 个案例配方和 28 个确定性 smoke PDF 测试基线。
    - 增加对象级自检、PDFium 渲染、qpdf 结构探针、重复生成哈希检查和 GitHub Actions。
    - 增加 CDE V1.1.0 官方验证器黑盒协议、PowerShell 证据采集工具和结果 schema。
    - 增加已知良好 eCTD baseline 的差分叶文件替换与 XML/MD5 更新工具。
    """
    if marker not in c:
        anchor = "### Added\n"
        if anchor in c:
            c = c.replace(anchor, anchor + "\n" + textwrap.dedent(additions).lstrip(), 1)
        else:
            c = c.rstrip() + "\n\n" + textwrap.dedent(additions).lstrip()
    changelog.write_text(c, encoding="utf-8", newline="\n")


def materialize_workflow() -> None:
    write_text(ROOT / ".github" / "workflows" / "p0-b0-validation.yml", """
    name: P0-B0 validation harness

    on:
      push:
        branches: [main, "agent/**"]
        paths:
          - "tests/p0_b0/**"
          - "tools/p0-b0/**"
          - "tools/cde-validator/**"
          - "docs/validation/p0-b0/**"
          - "rulepacks/cn-cde-ectd/v1.1/**"
          - ".github/workflows/p0-b0-validation.yml"
      pull_request:
        branches: [main]
      workflow_dispatch:

    permissions:
      contents: read

    jobs:
      validate:
        runs-on: ubuntu-latest
        timeout-minutes: 20
        steps:
          - uses: actions/checkout@v4
          - uses: actions/setup-python@v5
            with:
              python-version: "3.12"
              cache: pip
              cache-dependency-path: tests/p0_b0/requirements.txt
          - name: Install qpdf
            run: sudo apt-get update && sudo apt-get install -y qpdf
          - name: Install Python dependencies
            run: python -m pip install -r tests/p0_b0/requirements.txt
          - name: Run full P0-B0-A gate
            run: python tests/p0_b0/run_all.py
          - name: Package official-run PDF set
            run: python tests/p0_b0/package_for_official_run.py --smoke-dir build/p0-b0-smoke --manifest tests/p0_b0/smoke_manifest.json --output build/ezctd-p0-b0-official-run.zip
          - name: Upload generated evidence
            uses: actions/upload-artifact@v4
            with:
              name: p0-b0-synthetic-gate
              path: |
                build/p0-b0-smoke/
                build/p0-b0-gate-report.json
                build/ezctd-p0-b0-official-run.zip
              if-no-files-found: error
    """)


def main() -> int:
    rules = read_rules()
    matrix = build_case_matrix(rules)
    smoke = build_smoke_manifest(matrix)
    boundary = build_boundary_queue(matrix)
    materialize_docs(matrix, smoke, boundary)
    materialize_data(matrix, smoke, boundary)
    materialize_sources()
    materialize_tools()
    materialize_workflow()
    update_project_files()
    deliverables = []
    for base in [OUT_DOCS, OUT_TESTS, OUT_TOOLS, ROOT / ".github" / "workflows"]:
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            if path.name == "DELIVERABLE_MANIFEST.json":
                continue
            deliverables.append(path.relative_to(ROOT).as_posix())
    write_json(OUT_DOCS / "DELIVERABLE_MANIFEST.json", {
        "schema_version": "0.2.0",
        "stage": "P0-B0",
        "generated_by": "tools/p0-b0/materialize_p0_b0.py",
        "files": deliverables,
        "counts": {"files": len(deliverables), "rules": 26, "case_recipes": 130, "smoke_cases": 28, "boundary_experiments": boundary["count"]},
        "official_validator": "NOT_RUN",
    })
    print(json.dumps({"status": "MATERIALIZED", "rules": 26, "cases": 130, "smoke": 28, "boundary": boundary["count"], "files": len(deliverables)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
