---
name: write-claim
description: 把脑里的命题以 Gaia DSL claim() 形式落到 plan.gaia.py 中
---
# write-claim

## 何时用
你在思考时形成了一个具体命题，且认为它够成熟可以承诺到 plan.gaia.py 里（不是猜测；猜测请用 promote-obligation 走 SyntheticObligation）。

## 流程
1. 用 Read 读 plan.gaia.py
2. 选定一个有意义的小写 label（QID 正则要求 `[a-z_][a-z0-9_]*`，大写会被 graph_health 拒）
3. 用 Edit 在合适位置插入：
```python
my_label = claim(
    "<人类可读命题>",
    prior=<float in [0,1]>,
    metadata={"prior_justification": "<为何这个 prior>"},
)
```
4. 不要遗漏 prior_justification —— 否则 review 会出 prior_without_justification publish blocker。

## 不要做
- 不写大写 label（会编译失败）
- 不在已有节点的位置覆盖（用新 label）
- 不立即派 action（如需派，再调 /dispatch-action）
