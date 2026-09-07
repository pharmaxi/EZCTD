# EZCTD main 分支说明

main 暂保留早期规划基线和当前工程导航。最新应用、测试和详细开发约束位于 `agent/cro-pdf-safety-intake`。开始开发前检查远端 HEAD 和工作区；不要在缺少源码的 main 上重写一套实现，也不要未经授权合并整个研究历史。

当前目标是临床 CRO 的部分 PDF 工作台（模块 5、2.5、2.7），不是完整 eCTD Publisher。不要求完整申报包、XML 骨架或前五章零错误。

不覆盖输入或既有输出；不访问未授权目录；不提交真实临床 PDF、原始报告、受试者标识、密码或私钥。路径匹配不是内容身份，`.gitignore` 不是读取授权。未完成测试不得报告为通过。

切换到工程分支后，以该分支的 AGENTS.md、PROJECT_STATUS.md 和 docs/roadmap/CRO_DELIVERY.md 为开发入口。历史研究文件不能覆盖当前用户已确认的范围。
