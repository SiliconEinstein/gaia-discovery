#!/usr/bin/env python3
import json
from pathlib import Path
import time
from collections import Counter

workspace = Path("riemann_fixed_v3_20260414_165449")

while True:
    checkpoints_dir = workspace / "action_checkpoints"
    if checkpoints_dir.exists():
        checkpoints = list(checkpoints_dir.glob("*.json"))
        
        if checkpoints:
            print(f"\n=== 当前进度：{len(checkpoints)}次迭代 ===")
            
            # 统计模块使用
            modules = []
            outcomes = []
            
            for cp_path in sorted(checkpoints)[-10:]:  # 最近10次
                cp = json.loads(cp_path.read_text())
                module = cp.get('module')
                modules.append(module)
                
                if module == 'experiment':
                    result = cp.get('result', {})
                    normalized = result.get('normalized_output', {})
                    outcome = normalized.get('outcome')
                    outcomes.append(outcome)
                    
                    iter_num = cp.get('iteration')
                    print(f"  iter{iter_num}: {module} → outcome={outcome}")
            
            # 总体统计
            all_outcomes = []
            for cp_path in checkpoints:
                cp = json.loads(cp_path.read_text())
                if cp.get('module') == 'experiment':
                    result = cp.get('result', {})
                    normalized = result.get('normalized_output', {})
                    outcome = normalized.get('outcome')
                    all_outcomes.append(outcome)
            
            if all_outcomes:
                outcome_counts = Counter(all_outcomes)
                print(f"\n实验outcome统计（总{len(all_outcomes)}个）:")
                for outcome, count in outcome_counts.most_common():
                    print(f"  {outcome}: {count}次 ({count/len(all_outcomes)*100:.1f}%)")
                
                supported = outcome_counts.get('supported', 0)
                if supported > 0:
                    print(f"\n🎉 发现{supported}个supported实验！修复生效！")
        else:
            print("等待第一次迭代完成...")
    else:
        print("等待工作目录初始化...")
    
    time.sleep(60)  # 每分钟检查一次
