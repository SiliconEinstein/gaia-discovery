#!/usr/bin/env python3
"""
应用ingest.py的修复patch
精确替换refuted和weakened部分
"""
from pathlib import Path
import re

INGEST_FILE = Path("packages/dz-hypergraph/src/dz_hypergraph/ingest.py")

# 读取原文件
original = INGEST_FILE.read_text()

# ===== PATCH 1: refuted EXPERIMENT部分 =====
# 原代码 (lines 110-136)
old_refuted = '''        if module == Module.EXPERIMENT:
            penalty = float(output.get("confidence", 0.9))
            conclusion = output.get("conclusion")
            if not conclusion:
                return None
            conclusion_statement = (
                conclusion if isinstance(conclusion, str) else conclusion.get("statement", "")
            )
            existing = graph.find_node_ids_by_statement(conclusion_statement)
            if existing:
                node = graph.nodes[existing[0]]
                if not node.is_locked():
                    node.prior = max(CROMWELL_EPS, node.prior * (1.0 - penalty))
            else:
                weakened_belief = max(CROMWELL_EPS, 0.5 * (1.0 - penalty))
                graph.add_node(
                    statement=conclusion_statement,
                    belief=weakened_belief,
                    prior=weakened_belief,
                    domain=output.get("domain"),
                    provenance=provenance,
                )
            return None'''

# 新代码
new_refuted = '''        if module == Module.EXPERIMENT:
            # 实验refutation：创建contradiction边而非硬性设置state=refuted
            penalty = float(output.get("confidence", 0.9))
            conclusion = output.get("conclusion")
            if not conclusion:
                return None
            conclusion_statement = (
                conclusion if isinstance(conclusion, str) else conclusion.get("statement", "")
            )
            
            # 1. 找到或创建conclusion节点
            existing = graph.find_node_ids_by_statement(conclusion_statement)
            if existing:
                conclusion_id = existing[0]
                node = graph.nodes[conclusion_id]
                if not node.is_locked():
                    node.prior = max(CROMWELL_EPS, node.prior * (1.0 - penalty))
            else:
                refuted_belief = CROMWELL_EPS
                conclusion_node = graph.add_node(
                    statement=conclusion_statement,
                    belief=refuted_belief,
                    prior=refuted_belief,
                    domain=output.get("domain"),
                    provenance=provenance,
                )
                conclusion_id = conclusion_node.id
            
            # 2. 创建实验结果evidence节点（强refutation）
            experiment_statement = _build_experiment_evidence_statement(
                outcome="refuted",
                conclusion=conclusion_statement,
                confidence=penalty,
                summary=output.get("steps", ["Experiment contradicted the claim"])[0] if output.get("steps") else None
            )
            
            evidence_node = graph.add_node(
                statement=experiment_statement,
                belief=penalty,
                prior=penalty,
                domain=output.get("domain"),
                provenance=f"{provenance}_evidence",
                state="verified",
            )
            
            # 3. Idempotency检查
            premise_set = {evidence_node.id}
            already_exists = any(
                set(e.premise_ids) == premise_set and e.conclusion_id == conclusion_id
                for e in graph.edges.values()
            )
            if already_exists:
                return None
            
            # 4. 创建edge
            edge = graph.add_hyperedge(
                premise_ids=[evidence_node.id],
                conclusion_id=conclusion_id,
                module=module,
                steps=output.get("steps", []),
                confidence=CROMWELL_EPS,
                metadata={"outcome": "refuted", "penalty": penalty}
            )
            return edge'''

# 应用patch 1
if old_refuted in original:
    modified = original.replace(old_refuted, new_refuted)
    print("✅ Patch 1应用成功: refuted EXPERIMENT")
else:
    print("❌ Patch 1失败: 找不到匹配的原代码")
    modified = original

# ===== PATCH 2: weakened部分 =====
old_weakened = '''    if outcome == "weakened":
        # Soft refutation: reduce belief/prior proportionally but do NOT set state=refuted.
        # This allows BP to propagate a moderate negative signal without killing the node.
        conclusion = output.get("conclusion")
        if not conclusion:
            return None
        conclusion_statement = (
            conclusion if isinstance(conclusion, str) else conclusion.get("statement", "")
        )
        penalty = float(output.get("confidence", 0.3))
        existing = graph.find_node_ids_by_statement(conclusion_statement)
        if existing:
            node = graph.nodes[existing[0]]
            if not node.is_locked():
                node.prior = max(CROMWELL_EPS, node.prior * (1.0 - penalty))
        else:
            weakened_belief = max(CROMWELL_EPS, 0.5 * (1.0 - penalty))
            graph.add_node(
                statement=conclusion_statement,
                belief=weakened_belief,
                prior=weakened_belief,
                domain=output.get("domain"),
                provenance=provenance,
            )
        return None'''

new_weakened = '''    if outcome == "weakened":
        # Soft refutation: reduce belief/prior proportionally but do NOT set state=refuted.
        # This allows BP to propagate a moderate negative signal without killing the node.
        conclusion = output.get("conclusion")
        if not conclusion:
            return None
        conclusion_statement = (
            conclusion if isinstance(conclusion, str) else conclusion.get("statement", "")
        )
        penalty = float(output.get("confidence", 0.3))
        
        # 1. 找到或创建conclusion节点
        existing = graph.find_node_ids_by_statement(conclusion_statement)
        if existing:
            conclusion_id = existing[0]
            node = graph.nodes[conclusion_id]
            if not node.is_locked():
                node.prior = max(CROMWELL_EPS, node.prior * (1.0 - penalty))
        else:
            weakened_belief = max(CROMWELL_EPS, 0.5 * (1.0 - penalty))
            conclusion_node = graph.add_node(
                statement=conclusion_statement,
                belief=weakened_belief,
                prior=weakened_belief,
                domain=output.get("domain"),
                provenance=provenance,
            )
            conclusion_id = conclusion_node.id
        
        # 2. 创建实验结果evidence节点
        experiment_statement = _build_experiment_evidence_statement(
            outcome="weakened",
            conclusion=conclusion_statement,
            confidence=penalty,
            summary=output.get("steps", ["Experiment partially refuted the claim"])[0] if output.get("steps") else None
        )
        
        evidence_node = graph.add_node(
            statement=experiment_statement,
            belief=penalty,
            prior=penalty,
            domain=output.get("domain"),
            provenance=f"{provenance}_evidence",
            state="verified",
        )
        
        # 3. Idempotency检查
        premise_set = {evidence_node.id}
        already_exists = any(
            set(e.premise_ids) == premise_set and e.conclusion_id == conclusion_id
            for e in graph.edges.values()
        )
        if already_exists:
            return None
        
        # 4. 创建edge
        edge = graph.add_hyperedge(
            premise_ids=[evidence_node.id],
            conclusion_id=conclusion_id,
            module=module,
            steps=output.get("steps", []),
            confidence=1.0 - penalty,
            metadata={"outcome": "weakened", "penalty": penalty}
        )
        return edge'''

# 应用patch 2
if old_weakened in modified:
    modified = modified.replace(old_weakened, new_weakened)
    print("✅ Patch 2应用成功: weakened outcome")
else:
    print("❌ Patch 2失败: 找不到匹配的原代码")

# ===== PATCH 3: 添加辅助函数 =====
helper_function = '''

def _build_experiment_evidence_statement(
    outcome: str,
    conclusion: str,
    confidence: float,
    summary: str | None = None
) -> str:
    """构造实验结果evidence节点的statement。
    
    Args:
        outcome: "supported", "weakened", 或 "refuted"
        conclusion: 被验证的命题statement
        confidence: 实验confidence/penalty值
        summary: 可选的实验总结（来自steps[0]）
    
    Returns:
        格式化的evidence statement
    """
    if outcome == "supported":
        prefix = f"EXPERIMENTAL VERIFICATION (confidence={confidence:.2f})"
    elif outcome == "weakened":
        prefix = f"EXPERIMENTAL PARTIAL REFUTATION (penalty={confidence:.2f})"
    elif outcome == "refuted":
        prefix = f"EXPERIMENTAL CONTRADICTION (confidence={confidence:.2f})"
    else:
        prefix = f"EXPERIMENTAL RESULT ({outcome})"
    
    # 截断conclusion避免过长
    conclusion_short = conclusion[:150] + "..." if len(conclusion) > 150 else conclusion
    
    statement = f"{prefix}: {conclusion_short}"
    
    if summary:
        # 添加实验summary作为补充信息
        summary_short = summary[:100] + "..." if len(summary) > 100 else summary
        statement += f" | {summary_short}"
    
    return statement
'''

# 在文件末尾添加
modified += helper_function
print("✅ Patch 3应用成功: 添加辅助函数")

# 写入修改后的文件
INGEST_FILE.write_text(modified)
print(f"\n✅ 所有patch已应用到 {INGEST_FILE}")
print(f"   新文件行数: {len(modified.splitlines())}")

