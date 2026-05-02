---
name: promote-obligation
description: 把 SyntheticObligation 升级为 plan.gaia.py 中正式的 claim
---
# promote-obligation

## 何时用
之前 push 过 SyntheticObligation（还没 commit 的候选命题），现在 belief / 证据足够支撑它落成 claim。

## 流程
1. Read `.gaia/inquiry/state.json` 找到要升级的 obligation
2. 用 /write-claim 在 plan.gaia.py 写正式 claim()，prior 与 prior_justification 引用 obligation 的来源
3. Edit `.gaia/inquiry/state.json` 把那条 obligation 删掉（或 status=promoted）
4. append `memory/big_decisions.jsonl` 一条记录：obligation_id → claim_qid

## 不要做
- 不留 obligation 不删，会重复出现在下一轮 ProofContext
