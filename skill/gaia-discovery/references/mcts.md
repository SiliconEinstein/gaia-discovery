# MCTS Algorithm

## Overview

Monte Carlo Tree Search (MCTS) with UCB selection and progressive widening for scientific discovery.

## Algorithm

```
while iterations < max_iterations and time < max_time:
    # 1. Selection
    node = select_ucb(root)

    # 2. Expansion (Progressive Widening)
    if should_expand(node):
        child = expand(node)
    else:
        child = node

    # 3. Simulation (Bridge Planning)
    plan = generate_bridge_plan(child)
    reward = execute_plan(plan)

    # 4. Backpropagation
    backpropagate(child, reward)
```

## UCB Selection

```
UCB = Q(node) / N(node) + c_puct * sqrt(2 * ln(N(parent)) / N(node))
```

Where:
- `Q(node)`: Total reward
- `N(node)`: Visit count
- `c_puct`: Exploration coefficient (default 1.4)

## Progressive Widening

Controls expansion based on visit count:

```python
def should_expand(node):
    k = progressive_widening_constant
    alpha = progressive_widening_exponent
    return len(node.children) < k * (node.visits ** alpha)
```

## Bridge Planning

LLM-generated multi-step reasoning plans:

```python
class BridgePlan:
    propositions: List[Proposition]  # Ordered reasoning steps
    confidence: float                # Plan confidence
```

## Reward Function

```python
reward = belief_change - cost_penalty + verification_bonus
```

Where:
- `belief_change`: Target belief delta
- `cost_penalty`: Token/time cost
- `verification_bonus`: For verified claims

## HTPS Path Selection

Graph-aware leaf selection prioritizing:
1. High information gain paths
2. Unexplored reasoning directions
3. Promising analogy targets

## Virtual Loss

Prevents duplicate exploration:
```python
node.virtual_loss += 1  # During selection
node.virtual_loss -= 1  # After backpropagation
```

## Convergence

MCTS terminates when:
- `max_iterations` reached
- `max_time_seconds` exceeded
- Target belief >= threshold (optional)
- No improvement for N iterations (optional)

## Configuration

```python
MCTSConfig(
    max_iterations=50,
    max_time_seconds=14400,
    c_puct=1.4,
    enable_evolutionary_experiments=True,
    enable_continuation_verification=True,
)
```

## Expert Iteration

Experience records collected:
```python
@dataclass
class Experience:
    state: HyperGraph          # Graph state
    action: str                # Module action
    reward: float              # Reward received
    next_state: HyperGraph     # Resulting state
```

Used for offline RL training.
