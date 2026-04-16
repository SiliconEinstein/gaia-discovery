# Exploration Modules

## Overview

MCTS discovery uses multiple exploration modules, selected by UCB.

## Modules

### AnalogyEngine

Cross-domain analogical reasoning.

```python
from dz_engine.analogy import AnalogyEngine

engine = AnalogyEngine()
engine.domain_knowledge = load_kb("physics.json")

# Find analogies
analogies = engine.find_analogies(
    source_problem="target_conjecture",
    target_domain="physics",
)
```

**When to use**: Problem resembles known problems in other domains.

### DecomposeEngine

Problem decomposition into subgoals.

```python
from dz_engine.decompose import DecomposeEngine

engine = DecomposeEngine()

# Decompose problem
subgoals = engine.decompose(
    problem="complex_conjecture",
    max_depth=3,
)
```

**When to use**: Problem can be broken into smaller subproblems.

### SpecializeEngine

Problem specialization and generalization.

```python
from dz_engine.specialize import SpecializeEngine

engine = SpecializeEngine()

# Specialize
specialized = engine.specialize(
    problem="general_conjecture",
    direction="specific_case",
)

# Generalize
generalized = engine.generalize(
    problem="specific_case",
)
```

**When to use**: Need to test specific cases or find general patterns.

### KnowledgeRetriever

Knowledge retrieval and injection.

```python
from dz_engine.retrieve import KnowledgeRetriever

retriever = KnowledgeRetriever(
    embedding_api_base="https://...",
)

# Retrieve relevant knowledge
knowledge = retriever.retrieve(
    query="conjecture_statement",
    top_k=5,
)
```

**Requires**: `EMBEDDING_API_BASE` configured.

**When to use**: Need external knowledge for reasoning.

## Module Selection

UCB-based selection:

```python
module_scores = {
    "ANALOGY": ucb_score(analogy_stats),
    "DECOMPOSE": ucb_score(decompose_stats),
    "SPECIALIZE": ucb_score(specialize_stats),
    "EXPERIMENT": ucb_score(experiment_stats),
    "RETRIEVE": ucb_score(retrieve_stats),
}

selected = argmax(module_scores)
```

## Module Statistics

Each module tracks:
- Visit count
- Total reward
- Average reward
- Virtual loss

## Custom Modules

```python
from dz_engine.base import ExplorationModule

class CustomModule(ExplorationModule):
    def explore(self, graph, target_node):
        # Custom exploration logic
        return exploration_result

    def get_stats(self):
        return self.stats
```

Register with engine:
```python
engine = MCTSDiscoveryEngine(
    ...
    custom_module=CustomModule(),
)
```

## Configuration

```bash
# Enable/disable modules
DISCOVERY_ZERO_ENABLE_ANALOGY=true
DISCOVERY_ZERO_ENABLE_DECOMPOSE=true
DISCOVERY_ZERO_ENABLE_CLAIM_VERIFIER=true

# Retrieval requires embedding API
DISCOVERY_ZERO_ENABLE_RETRIVAL=false
EMBEDDING_API_BASE=https://...
```
