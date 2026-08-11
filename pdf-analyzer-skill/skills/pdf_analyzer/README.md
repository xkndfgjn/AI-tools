# PDF Analyzer Skill

这是一个面向 PDF 解析与分析的技能包。

## 作用
- 提取 PDF 文本
- 对扫描件进行 OCR 识别
- 生成 PDF 摘要
- 支持相关的 PDF 分析任务

## 关键目录
- plugin.json：插件元数据
- install.py：安装脚本
- build_min_skill.py：打包构建脚本
- skills/pdf_analyzer/skill.json：技能定义
- runtime/：运行时实现
- runtime/mcp_server/：MCP 服务端实现

## 使用建议
- 先看 skills/pdf_analyzer/skill.json 了解可用能力
- 再看 runtime 目录理解实际实现
- 如果需要打包或安装，优先查看 plugin.json 和 build_min_skill.py
