# CDE eCTD验证软件 V1.1.0 证据采集工具

该目录不包含CDE安装包，也不尝试逆向或自动操作官方软件。脚本只负责在Windows上固化运行环境、输入哈希和原始输出证据。

## 使用顺序

```powershell
# 1. 建立运行证据目录并记录输入/软件哈希
.\tools\official-validator\Prepare-CDEValidationRun.ps1 `
  -CaseId "CN-PDF-6_8-xyz-zero" `
  -SequencePath "D:\EZCTD\work\CN-PDF-6_8-xyz-zero\sequence" `
  -ValidatorExe "C:\Program Files\CDE eCTD Validator\validator.exe" `
  -EvidenceRoot ".\evidence\black-box"

# 2. 在官方软件中验证并把未经修改的报告导出到：
# evidence\black-box\<run-id>\raw-report\

# 3. 固化报告哈希并生成观察模板
.\tools\official-validator\Finalize-CDEValidationRun.ps1 `
  -RunDirectory ".\evidence\black-box\<run-id>"
```

## 证据要求

- 安装程序与实际可执行文件SHA-256；
- 操作手册SHA-256；
- Windows版本、区域、时区；
- 输入序列每个文件的相对路径、大小和SHA-256；
- 官方原始报告、截图或导出文件；
- 解析后的观察JSON；
- 同一输入重复运行结果。

未经上述证据支持，不得把矩阵中的`expected_cde`改成`CONFIRMED`。
