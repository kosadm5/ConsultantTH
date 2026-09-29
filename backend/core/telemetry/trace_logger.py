"""
backend/core/telemetry/trace_logger.py
Consultant+ Core Engine 2.0 — Comprehensive Agent Trace Logger.
Records complete request lifecycle, latencies, candidates, and rejection reasons.
"""

import os
import json
import time
from typing import Dict, Any, Optional
from contextlib import contextmanager

from core.models import AgentTrace, StageLatency, QueryPlan, ReasoningPlan, ClaimRecord


class AgentTraceLogger:
    def __init__(self, trace_dir: Optional[str] = None):
        self.trace_dir = trace_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "traces")
        os.makedirs(self.trace_dir, exist_ok=True)
        self.current_trace: Optional[AgentTrace] = None

    def start_trace(self, user_id: str, case_id: str, turn_index: int, input_type: str, raw_input: str) -> AgentTrace:
        self.current_trace = AgentTrace(
            user_id=user_id,
            case_id=case_id,
            turn_index=turn_index,
            input_type=input_type,
            raw_input=raw_input
        )
        return self.current_trace

    @contextmanager
    def measure_stage(self, stage_name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if self.current_trace:
                self.current_trace.latencies.append(
                    StageLatency(stage=stage_name, duration_ms=round(elapsed_ms, 2))
                )

    def record_case_before(self, case_state_dict: Dict[str, Any]):
        if self.current_trace:
            self.current_trace.case_state_before = case_state_dict

    def record_query_plan(self, plan: QueryPlan):
        if self.current_trace:
            self.current_trace.query_plan = plan

    def record_retrieval_counts(self, dense: int, lexical: int, graph: int, rrf: int, reranked: int):
        if self.current_trace:
            self.current_trace.retrieval_dense_count = dense
            self.current_trace.retrieval_lexical_count = lexical
            self.current_trace.retrieval_graph_count = graph
            self.current_trace.rrf_candidate_count = rrf
            self.current_trace.reranked_top_count = reranked

    def record_chunk_rejection(self, chunk_id: str, reason: str):
        if self.current_trace:
            self.current_trace.discarded_chunks_reasons[chunk_id] = reason

    def record_reasoning_plan(self, plan: ReasoningPlan):
        if self.current_trace:
            self.current_trace.reasoning_plan = plan

    def record_claims(self, claims: list[ClaimRecord]):
        if self.current_trace:
            self.current_trace.claims_evaluated = claims

    def record_issue_coverage(self, coverage: Dict[str, str]):
        if self.current_trace:
            self.current_trace.issue_coverage = coverage

    def record_case_after(self, case_state_dict: Dict[str, Any]):
        if self.current_trace:
            self.current_trace.case_state_after = case_state_dict

    def mark_fallback(self, degraded: bool = True):
        if self.current_trace:
            self.current_trace.fallback_triggered = True
            self.current_trace.degraded_mode = degraded

    def finalize_and_save(self) -> AgentTrace:
        if not self.current_trace:
            raise ValueError("No active trace to finalize")
        
        trace = self.current_trace
        # Persist to traces/trace_{trace_id}.json
        trace_path = os.path.join(self.trace_dir, f"trace_{trace.trace_id}.json")
        try:
            with open(trace_path, "w", encoding="utf-8") as f:
                f.write(trace.model_dump_json(indent=2))
        except Exception as e:
            # Fallback log without failing execution
            print(f"Warning: Failed to save trace {trace.trace_id}: {e}")
            
        self.current_trace = None
        return trace
