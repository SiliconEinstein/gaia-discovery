"""plan.gaia.py — 问题 {{__PROBLEM_ID__}} 的 Gaia 知识包 = 主 agent 的探索路径。

* 这个文件由主 agent 直接编辑（Edit / Write）。
* 它同时是:
    (a) 你对问题的当前形式化理解 (compile_package_artifact 直接吃)
    (b) 你的探索路径 (git diff 即可读)
* USER hint: 用户可在任意位置插入 `# USER: ...` 注释，主 agent 必须读并响应。
"""
from gaia.lang import (
    claim, setting, question,
    support, deduction, abduction, induction,
    contradiction, equivalence, complement, disjunction,
)

# ---------------------------------------------------------------------- 问题
# 主 agent: 阅读 PROBLEM.md, 把 open problem 的核心命题写为 question(...)
# 这是 target_qid 的来源，target.json 里登记的就是它。

q_main = question(
    "{{__QUESTION_TEXT__}}",
)

# ---------------------------------------------------------------------- setting
# 主 agent: 把问题域的不变量 / 假设作为 setting 写下来（例："n >= 2", "f 连续"）。
# setting 与 claim 不同：setting 是公认前提，不进 BP。

# ---------------------------------------------------------------------- claims
# 主 agent: 把候选命题以 claim() 形式写下来。
# 每个 claim 必须配 prior + prior_justification。
# 不会做的子问题用 metadata.action 标记派 sub-agent。
# 例：
#
# t = claim(
#     "target conclusion 的形式化陈述",
#     prior=0.5,
#     metadata={
#         "prior_justification": "see PROBLEM.md §1",
#     },
# )
#
# 然后用 strategy 连接（kwargs 风格，4 种）：
#
# deduction(premises=[lemma_a, lemma_b], conclusion=t)
#
# 或用 operator 标记关系（positional 风格，4 种；**不接 premises/conclusion**）：
#
# contradiction(assume_p, derive_not_p)
# equivalence(claim_a, claim_b)
# complement(branch_a, branch_b)
# disjunction(case_1, case_2, case_3)
#
# 注意：
# 1) operator 是 positional 二元/变元 Knowledge 参数；写成
#    `contradiction(premises=[...], conclusion=...)` 会直接 IR compile 422。
# 2) `reason` 与 `prior` 必须成对给（全给或全不给）；只给一个会触发
#    ValueError（_validate_reason_prior 校验）。例：
#       deduction(premises=[a, b], conclusion=t,
#                 reason="两个 lemma 推出 t", prior=0.9)
