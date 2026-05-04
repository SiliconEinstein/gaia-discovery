---
name: gaia-verify
description: escape hatch——单步对一份 evidence.json 调 verify-server :8092 拿 verdict，不写状态机
user_invocable: true
argument-hint: <project_dir> <action_id> --evidence <path>
---

# /gaia:verify

```bash
gd verify <project_dir> <action_id> --evidence <evidence.json>
```

debug 用。校验 evidence schema → POST :8092/verify → stdout `VerifyResponse`。

不写 plan、不动 cycle_state、不跑 BP。正轨请走 `/gaia:run-cycle`。
