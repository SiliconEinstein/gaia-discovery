"""精确修复ingest.py"""
from pathlib import Path

INGEST_PATH = Path("/root/gaia-discovery/packages/dz-hypergraph/src/dz_hypergraph/ingest.py")
content = INGEST_PATH.read_text()
lines = content.split('\n')

# 1. 找到refuted EXPERIMENT部分并修复 (line 110-136)
# 找到: if module == Module.EXPERIMENT:
refuted_experiment_start = None
for i, line in enumerate(lines):
    if 'if module == Module.EXPERIMENT:' in line and i > 100 and i < 115:
        refuted_experiment_start = i
        break

if refuted_experiment_start:
    # 找到这个if块的结束（下一个return None before if outcome == "weakened":）
    refuted_experiment_end = None
    for i in range(refuted_experiment_start, min(len(lines), refuted_experiment_start + 40)):
        if lines[i].strip() == 'return None' and i < 140:
            refuted_experiment_end = i
            break
    
    if refuted_experiment_end:
        # 替换这整个块
        indent = '        '
        new_block = [
            indent + '# 实验refutation：创建contradiction边而非硬性设置state=refuted',
            indent + 'penalty = float(output.get("confidence", 0.9))',
            indent + 'conclusion = output.get("conclusion")',
            indent + 'if not conclusion:',
            indent + '    return None',
            indent + 'conclusion_statement = (',
            indent + '    conclusion if isinstance(conclusion, str) else conclusion.get("statement", "")',
            indent + ')',
            indent + '',
            indent + '# 1. 找到或创建conclusion节点',
            indent + 'existing = graph.find_node_ids_by_statement(conclusion_statement)',
            indent + 'if existing:',
            indent + '    conclusion_id = existing[0]',
            indent + '    node = graph.nodes[conclusion_id]',
            indent + '    if not node.is_locked():',
            indent + '        node.prior = max(CROMWELL_EPS, node.prior * (1.0 - penalty))',
            indent + 'else:',
            indent + '    refuted_belief = CROMWELL_EPS',
            indent + '    conclusion_node = graph.add_node(',
            indent + '        statement=conclusion_statement,',
            indent + '        belief=refuted_belief,',
            indent + '        prior=refuted_belief,',
            indent + '        domain=output.get("domain"),',
            indent + '        provenance=provenance,',
            indent + '    )',
            indent + '    conclusion_id = conclusion_node.id',
            indent + '',
            indent + '# 2. 创建实验结果evidence节点（强refutation）',
            indent + 'experiment_statement = _build_experiment_evidence_statement(',
            indent + '    outcome="refuted",',
            indent + '    conclusion=conclusion_statement,',
            indent + '    confidence=penalty,',
            indent + '    summary=output.get("steps", ["Experiment contradicted the claim"])[0] if output.get("steps") else None',
            indent + ')',
            indent + '',
            indent + 'evidence_node = graph.add_node(',
            indent + '    statement=experiment_statement,',
            indent + '    belief=penalty,',
            indent + '    prior=penalty,',
            indent + '    domain=output.get("domain"),',
            indent + '    provenance=f"{provenance}_evidence",',
            indent + '    state="verified",',
            indent + ')',
            indent + '',
            indent + '# 3. Idempotency检查',
            indent + 'premise_set = {evidence_node.id}',
            indent + 'already_exists = any(',
            indent + '    set(e.premise_ids) == premise_set and e.conclusion_id == conclusion_id',
            indent + '    for e in graph.edges.values()',
            indent + ')',
            indent + 'if already_exists:',
            indent + '    return None',
            indent + '',
            indent + '# 4. 创建edge',
            indent + 'edge = graph.add_hyperedge(',
            indent + '    premise_ids=[evidence_node.id],',
            indent + '    conclusion_id=conclusion_id,',
            indent + '    module=module,',
            indent + '    steps=output.get("steps", []),',
            indent + '    confidence=CROMWELL_EPS,',
            indent + '    metadata={"outcome": "refuted", "penalty": penalty}',
            indent + ')',
            indent + 'return edge',
        ]
        
        lines = lines[:refuted_experiment_start+1] + new_block + lines[refuted_experiment_end+1:]

# 2. 找到weakened部分并修复 (line 155-176)
weakened_start = None
for i, line in enumerate(lines):
    if 'if outcome == "weakened":' in line:
        weakened_start = i
        break

if weakened_start:
    # 找到return None
    weakened_end = None
    for i in range(weakened_start, min(len(lines), weakened_start + 30)):
        if lines[i].strip() == 'return None':
            weakened_end = i
            break
    
    if weakened_end:
        # 找到existing赋值和add_node位置
        # 在existing[0]后添加conclusion_id赋值
        for i in range(weakened_start, weakened_end):
            if 'if existing:' in lines[i]:
                # 在下一行添加conclusion_id = existing[0]
                lines.insert(i+1, '            conclusion_id = existing[0]')
                weakened_end += 1
                break
        
        # 在else分支的add_node修改为conclusion_node = 并添加conclusion_id赋值
        for i in range(weakened_start, weakened_end):
            if 'graph.add_node(' in lines[i] and 'weakened_belief' in '\n'.join(lines[i:i+10]):
                lines[i] = lines[i].replace('graph.add_node(', 'conclusion_node = graph.add_node(')
                # 找到这个add_node的闭合括号
                bracket_count = 1
                j = i + 1
                while j < weakened_end and bracket_count > 0:
                    bracket_count += lines[j].count('(') - lines[j].count(')')
                    j += 1
                # 在闭合括号后添加conclusion_id赋值
                lines.insert(j, '            conclusion_id = conclusion_node.id')
                weakened_end += 1
                break
        
        # 替换return None
        indent = '        '
        new_ending = [
            indent + '',
            indent + '# 2. 创建实验结果evidence节点',
            indent + 'experiment_statement = _build_experiment_evidence_statement(',
            indent + '    outcome="weakened",',
            indent + '    conclusion=conclusion_statement,',
            indent + '    confidence=penalty,',
            indent + '    summary=output.get("steps", ["Experiment partially refuted the claim"])[0] if output.get("steps") else None',
            indent + ')',
            indent + '',
            indent + 'evidence_node = graph.add_node(',
            indent + '    statement=experiment_statement,',
            indent + '    belief=penalty,',
            indent + '    prior=penalty,',
            indent + '    domain=output.get("domain"),',
            indent + '    provenance=f"{provenance}_evidence",',
            indent + '    state="verified",',
            indent + ')',
            indent + '',
            indent + '# 3. Idempotency检查',
            indent + 'premise_set = {evidence_node.id}',
            indent + 'already_exists = any(',
            indent + '    set(e.premise_ids) == premise_set and e.conclusion_id == conclusion_id',
            indent + '    for e in graph.edges.values()',
            indent + ')',
            indent + 'if already_exists:',
            indent + '    return None',
            indent + '',
            indent + '# 4. 创建edge',
            indent + 'edge = graph.add_hyperedge(',
            indent + '    premise_ids=[evidence_node.id],',
            indent + '    conclusion_id=conclusion_id,',
            indent + '    module=module,',
            indent + '    steps=output.get("steps", []),',
            indent + '    confidence=1.0 - penalty,',
            indent + '    metadata={"outcome": "weakened", "penalty": penalty}',
            indent + ')',
            indent + 'return edge',
        ]
        
        lines = lines[:weakened_end] + new_ending + lines[weakened_end+1:]

# 3. 添加辅助函数到文件末尾
helper_func = '''

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

lines.append(helper_func)

# 写入修改后的内容
INGEST_PATH.write_text('\n'.join(lines))
print("✅ 修复完成")
print(f"   文件: {INGEST_PATH}")
print(f"   总行数: {len(lines)}")

