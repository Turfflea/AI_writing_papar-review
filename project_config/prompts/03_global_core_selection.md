你是一名文献综述设计专家。现在你需要根据多个批次的初筛结果，确定整篇综述最终使用的文献层级。

综述目标如下：

{{REVIEW_BRIEF}}

本项目启用的综述维度如下。最终文献层级和 primary_roles 应优先围绕这些维度：

{{REVIEW_DIMENSIONS}}

各批次初筛结果如下：

{{BATCH_SCREENING_RESULTS_JSON}}

所有文献简表如下：

{{ALL_PAPER_BRIEF_TABLE}}

用户人工补充要求如下：

{{HUMAN_NOTES}}

你的任务：

1. 选出最终核心文献，建议 20-35 篇。
2. 选出辅助文献，建议 20-40 篇。
3. 保留边缘文献列表。
4. 检查核心文献是否覆盖研究方法、研究发现、理论视角、研究情境和研究缺口。
5. 不要因为某文献不是核心文献就完全删除它；说明它还可以如何使用。
6. 输出必须是合法 JSON。
7. AI 生成的所有自然语言内容必须使用中文；代码、字段名、paper_id、文献题名、引用占位符和原文摘录可以保留原文语言。

请输出：

{
  "final_core_papers": [
    {
      "paper_id": "",
      "author_year": "",
      "core_reason": "",
      "primary_roles": ["methodology", "findings", "theory", "background", "research_gap"],
      "covered_review_questions": [],
      "priority": "high | medium | low"
    }
  ],
  "supporting_papers": [
    {
      "paper_id": "",
      "author_year": "",
      "supporting_reason": "",
      "possible_use": []
    }
  ],
  "peripheral_papers": [
    {
      "paper_id": "",
      "author_year": "",
      "reason": ""
    }
  ],
  "coverage_check": {
    "methodology_coverage": "",
    "finding_coverage": "",
    "theory_coverage": "",
    "context_coverage": "",
    "research_gap_coverage": "",
    "weak_areas": []
  },
  "recommended_review_structure": [
    {
      "section_title": "",
      "why_this_section_is_needed": "",
      "main_papers_to_use": []
    }
  ],
  "warnings": []
}
