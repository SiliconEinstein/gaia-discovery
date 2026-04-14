#!/bin/bash
for i in {1..10}; do
    echo "=== Check $i/10 $(date +%H:%M:%S) ==="
    
    # 检查进程
    if ! ps aux | grep -q "[r]un_upstream_5iter"; then
        echo "进程已结束"
        tail -50 upstream_5iter.log
        break
    fi
    
    # 检查checkpoint
    checkpoint_count=$(find upstream_5iter_*/action_checkpoints -name "*.json" 2>/dev/null | wc -l)
    echo "Checkpoints: $checkpoint_count"
    
    if [ $checkpoint_count -gt 0 ]; then
        echo "最新checkpoint:"
        latest=$(find upstream_5iter_*/action_checkpoints -name "*.json" 2>/dev/null | sort | tail -1)
        python3 << EOFPY
import json
data = json.load(open('$latest'))
r = data.get('result', {})
print(f"  module={r.get('selected_module')}, success={r.get('success')}, ingest_edge_id={r.get('ingest_edge_id')}")
EOFPY
    fi
    
    sleep 30
done
