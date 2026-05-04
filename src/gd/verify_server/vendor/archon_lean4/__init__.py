"""
Vendored Archon lean4 skill scripts.

Source       : https://github.com/frenzymath/Archon
Commit       : c504b1bfec9bd726e9a3f8c049ded2537964a280
Path in src  : src/archon/.archon-src/skills/lean4/scripts/
Files        :
  - sorry_analyzer.py        词法层 sorry 扫描（带 Lean 注释/字符串/嵌套 block-comment 解析）
  - check_axioms_inline.sh   在每个 declaration 后追加 #print axioms 抓真实公理闭包
  - parse_lean_errors.py     Lean 编译错误结构化（type_mismatch / failed_to_synth / 等）

License      : 见同目录 NOTICE 与 Archon 仓库 LICENSE 文件
Modification : NONE，逐字 cp，gaia 语义适配写在 ../audit/lean_audit.py 的 wrapper 中
"""
import os
from pathlib import Path

VENDOR_DIR = Path(__file__).parent
SORRY_ANALYZER = VENDOR_DIR / "sorry_analyzer.py"
CHECK_AXIOMS = VENDOR_DIR / "check_axioms_inline.sh"
PARSE_LEAN_ERRORS = VENDOR_DIR / "parse_lean_errors.py"

__all__ = ["VENDOR_DIR", "SORRY_ANALYZER", "CHECK_AXIOMS", "PARSE_LEAN_ERRORS"]
