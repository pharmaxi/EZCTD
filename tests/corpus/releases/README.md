# P0-B0a Smoke Corpus

P0-B0a 的 PDF 文件由生成器按需构造，不在 Git 中长期保存二进制副本。

```bash
python tools/corpus/build_pdf_fixtures.py \
  --output tests/corpus/generated-smoke \
  --mode smoke
python scripts/inspect_p0b0_smoke.py
```

当前基线：

- smoke 案例数：28；
- 本地对象级自检：28/28 通过；
- GitHub Actions 会在每次相关提交时重新生成并检查；
- 生成物位于 `tests/corpus/generated-smoke/`，已加入 `.gitignore`；
- 这些样本是对象级合成 PDF，不是完整、可提交的中国 eCTD 序列。

需要冻结某次二进制语料时，应在明确版本的 GitHub Release 或 Actions artifact 中保存，并同时保存 `manifest.json`、`local-inspection.json` 与 `SHA256SUMS.txt`。
