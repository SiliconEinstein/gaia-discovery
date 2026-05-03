#!/usr/bin/env python3
"""
gaia-discovery-v3 invariant checker.

Computes real counts from source-of-truth modules and validates against
CLAUDE.md prose. Replaces playground's web-app variant.

Truth sources:
    src/gd/verify_server/schemas.py — ALL_ACTIONS, STRATEGY_ACTIONS,
        OPERATOR_ACTIONS, ACTION_KIND_TO_ROUTER, ACTION_TO_STRATEGY
    .claude/agents/         — agent count
    .claude/skills/         — skill count

Usage:
    python scripts/check_invariants.py            # human table
    python scripts/check_invariants.py --json     # machine JSON
    python scripts/check_invariants.py --fix      # patch CLAUDE.md drift in-place

Exit codes:
    0  all checks pass
    1  one or more checks failed
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_schema_module():
    """Import gd.verify_server.schemas without polluting sys.path globally."""
    src = os.path.join(PROJECT_ROOT, 'src')
    if src not in sys.path:
        sys.path.insert(0, src)
    from gd.verify_server import schemas  # type: ignore
    return schemas


# ─── Check functions ────────────────────────────────────────────────────

def check_all_actions():
    s = _load_schema_module()
    n = len(s.ALL_ACTIONS)
    return {'value': n, 'expected': 8, 'ok': n == 8,
            'detail': sorted(getattr(a, 'value', str(a)) for a in s.ALL_ACTIONS)}


def check_strategy_actions():
    s = _load_schema_module()
    n = len(s.STRATEGY_ACTIONS)
    return {'value': n, 'expected': 4, 'ok': n == 4,
            'detail': sorted(getattr(a, 'value', str(a)) for a in s.STRATEGY_ACTIONS)}


def check_operator_actions():
    s = _load_schema_module()
    n = len(s.OPERATOR_ACTIONS)
    return {'value': n, 'expected': 4, 'ok': n == 4,
            'detail': sorted(getattr(a, 'value', str(a)) for a in s.OPERATOR_ACTIONS)}


def check_router_distribution():
    s = _load_schema_module()
    routers = [getattr(v, 'value', str(v)) for v in s.ACTION_KIND_TO_ROUTER.values()]
    dist = dict(Counter(routers))
    expected = {'quantitative': 1, 'structural': 1, 'heuristic': 6}
    return {'value': dist, 'expected': expected, 'ok': dist == expected,
            'detail': {getattr(k, 'value', str(k)): getattr(v, 'value', str(v))
                       for k, v in s.ACTION_KIND_TO_ROUTER.items()}}


def check_action_to_strategy():
    s = _load_schema_module()
    from gd import strategy_skeleton as sk
    m = getattr(sk, "ACTION_TO_STRATEGY", None)
    if m is None:
        return {'value': None, 'expected': 8, 'ok': False, 'detail': 'ACTION_TO_STRATEGY missing'}
    n = len(m)
    return {'value': n, 'expected': 8, 'ok': n == 8,
            'detail': {getattr(k, 'value', str(k)): getattr(v, 'value', str(v))
                       for k, v in m.items()}}


def check_agents_count():
    d = os.path.join(PROJECT_ROOT, '.claude', 'agents')
    files = sorted(f for f in os.listdir(d) if f.endswith('.md'))
    return {'value': len(files), 'expected': 12, 'ok': len(files) == 12, 'detail': files}


def check_skills_count():
    d = os.path.join(PROJECT_ROOT, '.claude', 'skills')
    dirs = sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x)))
    return {'value': len(dirs), 'expected': 15, 'ok': len(dirs) == 15, 'detail': dirs}


CHECKS = [
    ('ALL_ACTIONS == 8', check_all_actions),
    ('STRATEGY_ACTIONS == 4', check_strategy_actions),
    ('OPERATOR_ACTIONS == 4', check_operator_actions),
    ('ROUTER distribution (quant=1, struct=1, heur=6)', check_router_distribution),
    ('ACTION_TO_STRATEGY == 8', check_action_to_strategy),
    ('.claude/agents/ == 12', check_agents_count),
    ('.claude/skills/ == 15', check_skills_count),
]


# ─── CLAUDE.md drift detector ──────────────────────────────────────────

DRIFT_PATTERNS = [
    # (pattern, replacement_template, key in CHECKS results)
    (r'`ALL_ACTIONS == \d+`', '`ALL_ACTIONS == {value}`', 'ALL_ACTIONS == 8'),
    (r'`STRATEGY_ACTIONS == \d+`', '`STRATEGY_ACTIONS == {value}`', 'STRATEGY_ACTIONS == 4'),
    (r'`OPERATOR_ACTIONS == \d+`', '`OPERATOR_ACTIONS == {value}`', 'OPERATOR_ACTIONS == 4'),
    (r'`ACTION_TO_STRATEGY == \d+`', '`ACTION_TO_STRATEGY == {value}`', 'ACTION_TO_STRATEGY == 8'),
]


def detect_drift(results):
    claude_md = os.path.join(PROJECT_ROOT, 'CLAUDE.md')
    if not os.path.exists(claude_md):
        return []
    text = open(claude_md).read()
    drifts = []
    for pat, _, key in DRIFT_PATTERNS:
        m = re.search(pat, text)
        if m:
            current = m.group(0)
            actual = results[key]['value']
            expected_str = re.sub(r'\d+', str(actual), current)
            if current != expected_str:
                drifts.append((current, expected_str, key))
    return drifts


def fix_drift(drifts):
    claude_md = os.path.join(PROJECT_ROOT, 'CLAUDE.md')
    text = open(claude_md).read()
    for old, new, _ in drifts:
        text = text.replace(old, new)
    open(claude_md, 'w').write(text)


# ─── Output rendering ───────────────────────────────────────────────────

def render_table(results, drifts):
    print(f"{'Check':<55} {'Actual':<25} {'Expected':<25} {'OK'}")
    print('─' * 115)
    for name, r in results.items():
        ok = '✓' if r['ok'] else '✗'
        v = str(r['value'])[:24]
        e = str(r['expected'])[:24]
        print(f"{name:<55} {v:<25} {e:<25} {ok}")
    if drifts:
        print()
        print('CLAUDE.md drift detected:')
        for old, new, key in drifts:
            print(f"  [{key}] {old!r} → {new!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true', help='emit JSON')
    ap.add_argument('--fix', action='store_true', help='patch CLAUDE.md drift')
    args = ap.parse_args()

    results = {}
    all_ok = True
    for name, fn in CHECKS:
        try:
            r = fn()
        except Exception as e:
            r = {'value': None, 'expected': None, 'ok': False, 'detail': f'ERROR: {e}'}
        results[name] = r
        if not r['ok']:
            all_ok = False

    drifts = detect_drift(results)

    if args.fix:
        if drifts:
            fix_drift(drifts)
            print(f'Patched {len(drifts)} drift(s) in CLAUDE.md')
        else:
            print('No CLAUDE.md drift to fix')
        return 0

    if args.json:
        out = {'checks': results, 'drifts': [(o, n, k) for o, n, k in drifts], 'ok': all_ok and not drifts}
        print(json.dumps(out, indent=2, default=str))
    else:
        render_table(results, drifts)

    return 0 if (all_ok and not drifts) else 1


if __name__ == '__main__':
    sys.exit(main())
