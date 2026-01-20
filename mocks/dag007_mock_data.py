"""
DAG-007 Mock Data: Dynamic DAG Modification During Execution

This module provides mock data generators and utilities for testing
dynamic DAG modification scenarios.
"""

import asyncio
import json
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ModificationEvent:
    """Represents a DAG modification event."""
    timestamp: datetime
    modification_type: str  # 'add', 'remove', 'modify', 'replace'
    target_stage: str | None
    new_config: dict | None
    source: str  # 'interceptor', 'stage', 'external'
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class DAGModificationResult:
    """Result of a DAG modification attempt."""
    success: bool
    modification: ModificationEvent | None = None
    error: str | None = None
    post_state_stages: list[str] = field(default_factory=list)
    post_state_dependencies: dict = field(default_factory=dict)


class MockDAGModifier:
    """
    Simulates a DAG modification system.
    
    This mock tracks modification attempts and their results to test
    how Stageflow handles dynamic DAG changes during execution.
    """
    
    def __init__(self):
        self.modification_history: list[ModificationEvent] = []
        self._current_dag_state: dict = {}
        self._modification_count = 0
        self._failed_modifications = 0
        self._lock = asyncio.Lock()
    
    async def add_stage(
        self,
        stage_name: str,
        dependencies: list[str],
        config: dict | None = None
    ) -> DAGModificationResult:
        """Attempt to add a stage to the DAG."""
        async with self._lock:
            self._modification_count += 1
            event = ModificationEvent(
                timestamp=datetime.now(),
                modification_type='add',
                target_stage=stage_name,
                new_config=config or {},
                source='test',
            )
            self.modification_history.append(event)
            
            # Simulate modification logic
            if stage_name in self._current_dag_state:
                self._failed_modifications += 1
                return DAGModificationResult(
                    success=False,
                    error=f"Stage '{stage_name}' already exists",
                    modification=event,
                )
            
            # Add stage to internal state
            self._current_dag_state[stage_name] = {
                'dependencies': dependencies,
                'config': config or {},
                'status': 'pending',
            }
            
            return DAGModificationResult(
                success=True,
                modification=event,
                post_state_stages=list(self._current_dag_state.keys()),
                post_state_dependencies=self._current_dag_state,
            )
    
    async def remove_stage(self, stage_name: str) -> DAGModificationResult:
        """Attempt to remove a stage from the DAG."""
        async with self._lock:
            self._modification_count += 1
            event = ModificationEvent(
                timestamp=datetime.now(),
                modification_type='remove',
                target_stage=stage_name,
                new_config=None,
                source='test',
            )
            self.modification_history.append(event)
            
            if stage_name not in self._current_dag_state:
                self._failed_modifications += 1
                return DAGModificationResult(
                    success=False,
                    error=f"Stage '{stage_name}' does not exist",
                    modification=event,
                )
            
            # Remove stage and any references to it
            del self._current_dag_state[stage_name]
            for dep_list in self._current_dag_state.values():
                if stage_name in dep_list['dependencies']:
                    dep_list['dependencies'].remove(stage_name)
            
            return DAGModificationResult(
                success=True,
                modification=event,
                post_state_stages=list(self._current_dag_state.keys()),
                post_state_dependencies=self._current_dag_state,
            )
    
    async def replace_pipeline(self, new_dag_config: dict) -> DAGModificationResult:
        """Attempt to replace the entire DAG configuration."""
        async with self._lock:
            self._modification_count += 1
            event = ModificationEvent(
                timestamp=datetime.now(),
                modification_type='replace',
                target_stage=None,
                new_config=new_dag_config,
                source='test',
            )
            self.modification_history.append(event)
            
            self._current_dag_state = new_dag_config
            
            return DAGModificationResult(
                success=True,
                modification=event,
                post_state_stages=list(new_dag_config.keys()),
                post_state_dependencies=new_dag_config,
            )
    
    def get_stats(self) -> dict:
        """Get modification statistics."""
        return {
            'total_modifications': self._modification_count,
            'failed_modifications': self._failed_modifications,
            'success_rate': (
                (self._modification_count - self._failed_modifications) / 
                self._modification_count * 100 if self._modification_count > 0 else 100
            ),
            'current_state': self._current_dag_state,
            'history_length': len(self.modification_history),
        }


class DynamicWorkloadGenerator:
    """
    Generates workloads that require dynamic DAG modification.
    
    Simulates scenarios where the workload changes during execution,
    requiring the pipeline to adapt.
    """
    
    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
    
    async def generate_variable_workload(
        self,
        base_items: int = 10,
        variability: float = 0.5
    ) -> list[dict]:
        """
        Generate a variable workload that may change during execution.
        
        Args:
            base_items: Base number of items to process
            variability: How much the workload can vary (0-1)
        
        Returns:
            List of work items
        """
        # Initial workload
        items = []
        for i in range(base_items):
            items.append({
                'item_id': i,
                'type': random.choice(['A', 'B', 'C']),
                'priority': random.randint(1, 5),
                'processing_time': random.uniform(0.01, 0.1),
            })
        
        # Simulate runtime changes (some items added, some removed)
        if random.random() < variability:
            # Add new items
            num_additions = random.randint(1, 5)
            for i in range(num_additions):
                items.append({
                    'item_id': base_items + i,
                    'type': random.choice(['A', 'B', 'C']),
                    'priority': random.randint(1, 5),
                    'processing_time': random.uniform(0.01, 0.1),
                    'added_runtime': True,  # Mark as runtime addition
                })
        
        if random.random() < variability:
            # Remove some items
            num_removals = min(random.randint(0, 3), len(items) - 1)
            for _ in range(num_removals):
                # Don't remove the first item
                idx = random.randint(1, len(items) - 1)
                items.pop(idx)
        
        return items
    
    async def generate_adaptive_workload(self, stages: int = 5) -> dict:
        """
        Generate a workload that triggers adaptive behavior.
        
        Returns:
            Dict with stage configurations that may change
        """
        config = {}
        for i in range(stages):
            config[f"stage_{i}"] = {
                'enabled': random.random() > 0.2,  # 80% chance enabled
                'parallelism': random.randint(1, 4),
                'timeout': random.uniform(1.0, 10.0),
                'retry_count': random.randint(0, 3),
                'conditional_on': None,  # Could reference other stages
            }
        
        # Add some conditional dependencies
        for i in range(1, stages):
            if random.random() > 0.5:
                config[f"stage_{i}"]["conditional_on"] = f"stage_{i-1}"
        
        return config


class CycleDetector:
    """
    Utility to detect cycles in DAG modifications.
    
    Useful for testing that dynamic modifications don't create cycles.
    """
    
    @staticmethod
    def detect_cycle(stages: dict) -> list[str] | None:
        """
        Detect if adding/modifying dependencies creates a cycle.
        
        Uses DFS to find cycles in the dependency graph.
        
        Returns:
            List of stages forming the cycle, or None if no cycle
        """
        # Build adjacency list
        adj = {stage: set() for stage in stages}
        for stage, config in stages.items():
            deps = config.get('dependencies', [])
            if isinstance(deps, str):
                deps = [deps]
            for dep in deps:
                if dep in adj:
                    adj[stage].add(dep)
        
        # DFS-based cycle detection
        visited = set()
        recursion_stack = set()
        
        def dfs(node: str) -> list[str] | None:
            if node in recursion_stack:
                return [node]
            if node in visited:
                return None
            
            visited.add(node)
            recursion_stack.add(node)
            
            for neighbor in adj[node]:
                cycle = dfs(neighbor)
                if cycle:
                    if cycle[0] == node:
                        return cycle
                    return [node] + cycle
            
            recursion_stack.remove(node)
            return None
        
        for stage in adj:
            if stage not in visited:
                cycle = dfs(stage)
                if cycle:
                    return cycle
        
        return None
    
    @staticmethod
    def would_create_cycle(
        current_stages: dict,
        stage_to_add: str,
        new_dependencies: list[str]
    ) -> tuple[bool, str | None]:
        """
        Check if adding a stage with given dependencies would create a cycle.
        
        Returns:
            (would_create_cycle, cycle_path_or_none)
        """
        # Create a temporary combined dict
        temp_stages = dict(current_stages)
        temp_stages[stage_to_add] = {'dependencies': new_dependencies}
        
        cycle = CycleDetector.detect_cycle(temp_stages)
        return cycle is not None, cycle


# Test configuration presets
DYNAMIC_DAG_TEST_CONFIGS = {
    'baseline': {
        'num_stages': 5,
        'modifications': [],
        'expected_outcome': 'success',
    },
    'simple_add': {
        'num_stages': 3,
        'modifications': [
            {'type': 'add', 'stage': 'dynamic_stage', 'deps': ['stage_1']}
        ],
        'expected_outcome': 'success',
    },
    'parallel_add': {
        'num_stages': 3,
        'modifications': [
            {'type': 'add', 'stage': 'dynamic_1', 'deps': ['stage_1']},
            {'type': 'add', 'stage': 'dynamic_2', 'deps': ['stage_2']},
        ],
        'expected_outcome': 'success',
    },
    'cycle_attempt': {
        'num_stages': 3,
        'modifications': [
            {'type': 'add', 'stage': 'cycle_stage', 'deps': ['stage_3']}
        ],
        'expected_outcome': 'failure',  # Would create cycle
    },
    'orphan_stage': {
        'num_stages': 3,
        'modifications': [
            {'type': 'add', 'stage': 'orphan', 'deps': ['nonexistent']}
        ],
        'expected_outcome': 'failure',  # Missing dependency
    },
    'concurrent_modification': {
        'num_stages': 3,
        'modifications': [
            {'type': 'add', 'stage': 'concurrent_1', 'deps': ['stage_1']},
            {'type': 'add', 'stage': 'concurrent_2', 'deps': ['stage_2']},
            {'type': 'add', 'stage': 'concurrent_3', 'deps': ['stage_3']},
        ],
        'expected_outcome': 'partial',  # Some may fail
    },
    'pipeline_swap': {
        'num_stages': 3,
        'modifications': [
            {'type': 'replace', 'config': {'new_stage': {'deps': []}}}
        ],
        'expected_outcome': 'success',
    },
}
