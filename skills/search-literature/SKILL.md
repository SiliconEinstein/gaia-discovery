---
name: search-literature
description: 用 OpenAlex / arXiv / CrossRef API 检索学术文献（科学 open problem 必备）
---
# search-literature

## 何时用
- 攻 open problem 时定位已有结果 / 反例 / 相关定理
- 写 prior_justification / provenance 时确认引用
- bridge_planning 时寻找跳板 lemma
- adaptive control loop 的 Step 2 D 阶段（探索盲区且文献不足）

## 不允许
- **禁用 WebSearch 工具**（用户全局指令规定）
- **禁用 DuckDuckGo**（大陆不可达）

## API 优先级（用户全局规定）
1. OpenAlex（首选，免费无 key，覆盖广，有引用量）
2. arXiv（最新预印本，有完整摘要）
3. CrossRef（DOI 与正式发表信息）
4. Semantic Scholar（引用关系图谱）

## 流程

### 1) OpenAlex 标题搜索（首选）
```bash
curl -sL "https://api.openalex.org/works?filter=title.search:KEYWORD,publication_year:2018-2026&per_page=10&sort=cited_by_count:desc&select=id,title,doi,publication_year,cited_by_count"
```

### 2) OpenAlex 全文搜索
```bash
curl -sL "https://api.openalex.org/works?search=KEYWORD&per_page=10&sort=cited_by_count:desc&select=id,title,doi,publication_year,cited_by_count"
```

### 3) arXiv（最新预印本）
```bash
curl -sL "http://export.arxiv.org/api/query?search_query=ti:KEYWORD+AND+cat:math.NT&max_results=10&sortBy=submittedDate&sortOrder=descending"
```
- 精确短语：`ti:%22exact+phrase%22`
- 限流时等 5 秒再重试

### 4) CrossRef
```bash
curl -sL "https://api.crossref.org/works?query=KEYWORD&rows=10&select=DOI,title,author,published-print,container-title"
```

### 5) 拿到 URL 后细读
```bash
# WebFetch 工具可用
```

## 落档
找到的关键引用必须：
1. `memory_append` 到 `memory/big_decisions.jsonl` 或 `immediate_conclusions.jsonl`
2. 写进 plan.gaia.py 中相关 claim 的 `metadata={"prior_justification": "see [Author Year]", "refs": ["doi:..."]}`
3. 全文 PDF / 关键段落可下载到 `task_results/refs/<slug>.{pdf,md}`（不是核心代码区）

## sub-agent 共用
本 skill 不只主 agent 用——subagent 类型为 `support` / `abduction` 时也优先
调用本 skill 而非凭直觉编引用。
