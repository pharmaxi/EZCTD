# PDF Fixture Builder

```bash
python -m pip install -r requirements-corpus.txt
python tools/corpus/build_pdf_fixtures.py --output tests/corpus/generated
python scripts/validate_p0b0_matrix.py
```

生成器只创建合成PDF，不读取真实申报资料。每个案例目录包含主PDF、必要的目标PDF以及`case.json`；根目录生成`manifest.json`。

当前生成器覆盖规则结构研究所需的多数低层对象。`blocked`配方依赖qpdf、真实PDF/A转换器、字体文件或数字签名工具，不会伪造为已实现。

二进制fixture可在开发分支生成；正式仓库是否提交全部二进制样本，待体积和许可证复核后决定。manifest和生成器必须提交。

## 当前自检状态

- 规则矩阵：26条 / 163个案例。
- 可执行配方：130个。
- smoke集合：28个案例，结构自检28/28通过。
- 除6.16专门版本样本外，生成器基线统一为PDF 1.7。
- 生成器尚不负责构建有效Fast Web View；在纳入官方序列前需由qpdf线性化或放入明确豁免上下文，并记录由此产生的baseline noise。
- 合成PDF只验证对象结构，不等同于完整有效eCTD序列。
