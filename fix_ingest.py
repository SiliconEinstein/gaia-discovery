"""修复ingest.py，添加experiment evidence edges"""

import re
from pathlib import Path

INGEST_PATH = Path("/root/gaia-discovery/packages/dz-hypergraph/src/dz_hypergraph/ingest.py")

# 读取原文件
content = INGEST_PATH.read_text()

# 1. 添加辅助函数（在文件末尾before最后一个函数）
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

# 2. 修复weakened outcome处理
# 找到weakened部分的return None并替换
weakened_fix = '''        # 2. 创建实验结果evidence节点
        experiment_statement = _build_experiment_evidence_statement(
            outcome="weakened",
            conclusion=conclusion_statement,
            confidence=penalty,
            summary=output.get("steps", ["Experiment partially refuted the claim"])[0] if output.get("steps") else None
        )
        
        evidence_node = graph.add_node(
            statement=experiment_statement,
            belief=penalty,  # penalty值反映evidence强度
            prior=penalty,
            domain=output.get("domain"),
            provenance=f"{provenance}_evidence",
            state="verified",  # 实验结果是已验证的
        )
        
        # 3. Idempotency检查：如果已有相同的evidence edge，跳过创建
        # 参考bridge.py的模式：检查是否存在相同premise和conclusion的edge
        premise_set = {evidence_node.id}
        already_exists = any(
            set(e.premise_ids) == premise_set and e.conclusion_id == conclusion_id
            for e in graph.edges.values()
        )
        
        if already_exists:
            # 已存在相同的验证edge，不重复创建
            return None
        
        # 4. 创建edge: evidence → conclusion (negative support)
        edge = graph.add_hyperedge(
            premise_ids=[evidence_node.id],
            conclusion_id=conclusion_id,
            module=module,
            steps=output.get("steps", []),
            confidence=1.0 - penalty,  # 负向证据：1-penalty
            metadata={"outcome": "weakened", "penalty": penalty}
        )
        
        return edge'''

# 3. 修复refuted outcome for EXPERIMENT
refuted_fix = '''        # 1. 找到或创建conclusion节点
        existing = graph.find_node_ids_by_statement(conclusion_statement)
        if existing:
            conclusion_id = existing[0]
            node = graph.nodes[conclusion_id]
            if not node.is_locked():
                # 强烈削弱prior（但不设为0，保留BP恢复可能）
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
        
        # 3. Idempotency检查：如果已有相同的evidence edge，跳过创建
        premise_set = {evidence_node.id}
        already_exists = any(
            set(e.premise_ids) == premise_set and e.conclusion_id == conclusion_id
            for e in graph.edges.values()
        )
        
        if already_exists:
            # 已存在相同的验证edge，不重复创建
            return None
        
        # 4. 创建edge: evidence → conclusion (strong negative)
        edge = graph.add_hyperedge(
            premise_ids=[evidence_node.id],
            conclusion_id=conclusion_id,
            module=module,
            steps=output.get("steps", []),
            confidence=CROMWELL_EPS,  # 接近0的confidence表示强refutation
            metadata={"outcome": "refuted", "penalty": penalty}
        )
        
        return edge'''

# 执行替换
lines = content.split('\n')
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    
    # 检测weakened部分的return None (在第176行附近)
    if i > 150 and i < 180 and line.strip() == 'return None' and 'weakened' in '\n'.join(lines[max(0,i-20):i]):
        # 找到前面的conclusion_id赋值
        # 回溯找到conclusion_id = existing[0]或conclusion_id = conclusion_node.id
        needs_conclusion_id = True
        for j in range(i-1, max(0, i-30), -1):
            if 'conclusion_id' in lines[j]:
                needs_conclusion_id = False
                break
        
        if needs_conclusion_id:
            # 需要在前面添加conclusion_id赋值逻辑
            # 找到else: graph.add_node 的位置
            for j in range(i-1, max(0, i-15), -1):
                if 'graph.add_node(' in lines[j] and 'weakened_belief' in '\n'.join(lines[j:i]):
                    # 在)后添加.id赋值
                    # 找到这个add_node的结尾
                    bracket_count = 0
                    for k in range(j, i):
                        bracket_count += lines[k].count('(') - lines[k].count(')')
                        if bracket_count == 0:
                            # 找到了闭合括号的行
                            indent = ' ' * 12
                            new_lines.append(indent + 'conclusion_node = graph.add_node(')
                            # 复制中间的行，但第一行去掉graph.add_node(
                            new_lines.extend(lines[j+1:k+1])
                            new_lines.append(indent + 'conclusion_id = conclusion_node.id')
                            i = k + 1
                            break
                    break
            # 处理existing分支
            for j in range(i-1, max(0, i-30), -1):
                if 'if existing:' in lines[j]:
                    # 在existing分支也需要添加conclusion_id
                    insert_pos = j + 1
                    while insert_pos < i and not lines[insert_pos].strip().startswith('node ='):
                        insert_pos += 1
                    if insert_pos < i:
                        indent = ' ' * 12
                        new_lines.insert(len(new_lines) - (i - insert_pos - 1), indent + 'conclusion_id = existing[0]')
                    break
        
        # 替换return None
        new_lines.extend(weakened_fix.split('\n'))
        i += 1
        continue
    
    # 检测refuted EXPERIMENT部分的return None (在第136行附近)  
    if i > 100 and i < 140 and line.strip() == 'return None' and 'EXPERIMENT' in '\n'.join(lines[max(0,i-40):i]) and 'penalty = float' in '\n'.join(lines[max(0,i-10):i]):
        # 替换整个if existing...else...部分加return None
        # 回溯找到if existing:
        start_pos = i
        for j in range(i-1, max(0, i-25), -1):
            if lines[j].strip().startswith('if existing:'):
                start_pos = j
                break
        # 删除从if existing到return None的所有行
        del new_lines[-(i - start_pos + 1):]
        # 添加新代码
        new_lines.extend(refuted_fix.split('\n'))
        i += 1
        continue
    
    new_lines.append(line)
    i += 1

# 添加辅助函数到文件末尾
final_content = '\n'.join(new_lines)
# 在最后一个函数之前插入
last_def_pos = final_content.rfind('\ndef ')
if last_def_pos > 0:
    final_content = final_content[:last_def_pos] + helper_function + '\n' + final_content[last_def_pos:]
else:
    final_content += helper_function

# 备份原文件
backup_path = INGEST_PATH.parent / "ingest.py.backup"
backup_path.write_text(content)
print(f"✅ 备份原文件到: {backup_path}")

# 写入修改后的内容
INGEST_PATH.write_text(final_content)
print(f"✅ 已修改 {INGEST_PATH}")
print(f"   添加了 _build_experiment_evidence_statement 辅助函数")
print(f"   修复了 weakened outcome处理（创建evidence edges）")
print(f"   修复了 refuted EXPERIMENT outcome处理（创建evidence edges）")
print(f"   添加了 idempotency检查（防止重复验证）")

