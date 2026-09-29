"""
backend/core/benchmarks/reranker_benchmark.py
Consultant+ Core Engine 2.0 — Empirical Reranker Benchmark.
Measures NDCG@5, MRR, Precision@3, and CPU Latency across candidate cross-encoders
on multilingual legal queries (RU/EN -> Thai/English legal chunks).
"""

import time
import math
import json
from typing import List, Dict, Any
from fastembed.rerank.cross_encoder import TextCrossEncoder

# ─────────────────────────────────────────────────────────────────────────────
# 1. EVALUATION DATASET: Real Multilingual Thai Legal Queries & Candidates
# ─────────────────────────────────────────────────────────────────────────────
BENCHMARK_CASES = [
    {
        "id": "prop_01",
        "query": "Как иностранному гражданину законно купить квартиру в кондоминиуме в Таиланде в личную собственность?",
        "candidates": [
            {
                "text": "Section 19 Condominium Act B.E. 2522: Aliens and juristic persons regarded by law as aliens may hold ownership of an apartment if they are permitted to have residence in the Kingdom, brought foreign currency into the Kingdom, or transferred funds through bank Foreign Exchange Transaction FET certificate within the 49 percent aggregate floor area quota.",
                "relevant": 1
            },
            {
                "text": "Land Code Section 86: Aliens may acquire land only by virtue of the provisions of a treaty giving the right to own immovable property.",
                "relevant": 0
            },
            {
                "text": "Civil and Commercial Code Section 538: A hire of immovable property is not enforceable by action unless there be some written evidence signed by the party liable.",
                "relevant": 0
            },
            {
                "text": "Supreme Court Precedent San Deka: Foreign national transferring foreign currency for condominium purchase complies with Section 19(5) of Condominium Act and retains indefeasible freehold rights.",
                "relevant": 1
            }
        ]
    },
    {
        "id": "prop_02",
        "query": "Может ли иностранец оформить виллу и землю на тайскую компанию со своими знакомыми тайцами?",
        "candidates": [
            {
                "text": "Foreign Business Act B.E. 2542 Section 36: A Thai national who acts as a nominee holding shares or interest on behalf of a foreigner to circumvent foreign business limitations shall be liable to imprisonment up to three years or a fine of 100,000 to 1,000,000 Baht.",
                "relevant": 1
            },
            {
                "text": "Land Department Order: Land Officers are instructed to strictly interrogate and inspect the financial background and source of funds of Thai shareholders in companies with foreign directors acquiring land to prevent illegal nominee shareholding.",
                "relevant": 1
            },
            {
                "text": "Section 1410 Civil and Commercial Code: The owner of a piece of land may create a right of superficies in favor of another person by giving him the right to own buildings on or under the land.",
                "relevant": 0
            },
            {
                "text": "Revenue Department Order Paw. 161/2566 regarding personal income tax for individuals bringing foreign-sourced income into Thailand.",
                "relevant": 0
            }
        ]
    },
    {
        "id": "tax_01",
        "query": "Нужно ли платить налог в Таиланде при ввозе денег заработанных за границей в прошлом году?",
        "candidates": [
            {
                "text": "Revenue Department Instruction Paw. 161/2566: A tax resident residing in Thailand for a total of 180 days or more in a tax year who derives assessable income from employment or business abroad shall pay personal income tax when bringing said income into Thailand.",
                "relevant": 1
            },
            {
                "text": "Revenue Department Clarification Paw. 162/2566: Instruction Paw. 161/2566 shall only apply to assessable income derived from foreign sources starting from 1 January 2024 onwards. Savings or assets accumulated prior to 2024 are exempt from Thai PIT upon remittance.",
                "relevant": 1
            },
            {
                "text": "Labor Protection Act Section 118: An employer who terminates employment without statutory fault must pay severance pay according to the employee's length of service.",
                "relevant": 0
            },
            {
                "text": "Hotel Act B.E. 2547: Providing guest accommodation for remuneration on a daily basis requires a formal hotel business operating license issued by the provincial registrar.",
                "relevant": 0
            }
        ]
    },
    {
        "id": "hotel_01",
        "query": "Можно ли сдавать виллу туристам посуточно через Airbnb без гостиничной лицензии?",
        "candidates": [
            {
                "text": "Hotel Act B.E. 2547 Section 15 and Supreme Court Precedent: Renting out residential villa or condominium units to transient tourists on a daily or weekly basis constitutes operating a hotel business without a license under Section 59, punishable by imprisonment up to one year.",
                "relevant": 1
            },
            {
                "text": "Ministerial Regulation under Hotel Act: Residential premises having no more than 4 rooms and accommodating no more than 20 guests may be registered as non-hotel accommodations exempt from standard hotel building regulations provided formal notification is filed with the district office.",
                "relevant": 1
            },
            {
                "text": "Condominium Act Section 19/1: The transfer of an apartment to an alien must be accompanied by evidence of inward remittance of foreign exchange.",
                "relevant": 0
            },
            {
                "text": "Civil and Commercial Code Section 1465: Premarital agreements must be made in writing and registered in the marriage registry.",
                "relevant": 0
            }
        ]
    }
]


# ─────────────────────────────────────────────────────────────────────────────
# 2. EVALUATION METRIC CALCULATIONS
# ─────────────────────────────────────────────────────────────────────────────

def calculate_dcg(relevances: List[int], k: int = 5) -> float:
    dcg = 0.0
    for i, rel in enumerate(relevances[:k]):
        dcg += (2**rel - 1) / math.log2(i + 2)
    return dcg

def calculate_ndcg(relevances: List[int], k: int = 5) -> float:
    actual_dcg = calculate_dcg(relevances, k)
    ideal_dcg = calculate_dcg(sorted(relevances, reverse=True), k)
    if ideal_dcg == 0.0:
        return 0.0
    return actual_dcg / ideal_dcg

def calculate_mrr(relevances: List[int]) -> float:
    for i, rel in enumerate(relevances):
        if rel > 0:
            return 1.0 / (i + 1)
    return 0.0

def calculate_precision_at_k(relevances: List[int], k: int = 3) -> float:
    if not relevances[:k]:
        return 0.0
    return sum(relevances[:k]) / float(k)


# ─────────────────────────────────────────────────────────────────────────────
# 3. BENCHMARK EXECUTION HARNESS
# ─────────────────────────────────────────────────────────────────────────────

def run_reranker_benchmark(models_to_test: List[str]) -> Dict[str, Any]:
    benchmark_results = {}

    for model_name in models_to_test:
        print(f"\n=======================================================")
        print(f"Benchmarking Model: {model_name}")
        print(f"=======================================================")
        
        load_start = time.perf_counter()
        try:
            reranker = TextCrossEncoder(model_name=model_name)
        except Exception as e:
            print(f"Failed to load {model_name}: {e}")
            continue
        load_time_sec = round(time.perf_counter() - load_start, 2)
        print(f"Loaded in {load_time_sec}s")

        ndcg_scores = []
        mrr_scores = []
        p3_scores = []
        latencies_ms = []

        for case in BENCHMARK_CASES:
            query = case["query"]
            cands = case["candidates"]
            texts = [c["text"] for c in cands]
            ground_truth = [c["relevant"] for c in cands]

            # Measure inference time
            t0 = time.perf_counter()
            scores = list(reranker.rerank(query, texts))
            t_elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(t_elapsed_ms)

            # Pair candidate with score and ground truth
            ranked_pairs = sorted(zip(scores, ground_truth), key=lambda x: x[0], reverse=True)
            ranked_relevances = [p[1] for p in ranked_pairs]

            ndcg = calculate_ndcg(ranked_relevances, k=5)
            mrr = calculate_mrr(ranked_relevances)
            p3 = calculate_precision_at_k(ranked_relevances, k=3)

            ndcg_scores.append(ndcg)
            mrr_scores.append(mrr)
            p3_scores.append(p3)

        avg_ndcg = round(sum(ndcg_scores) / len(ndcg_scores), 4)
        avg_mrr = round(sum(mrr_scores) / len(mrr_scores), 4)
        avg_p3 = round(sum(p3_scores) / len(p3_scores), 4)
        avg_latency = round(sum(latencies_ms) / len(latencies_ms), 2)

        print(f"Results for {model_name}:")
        print(f"  NDCG@5:       {avg_ndcg:.4f}")
        print(f"  MRR:          {avg_mrr:.4f}")
        print(f"  Precision@3:  {avg_p3:.4f}")
        print(f"  CPU Latency:  {avg_latency:.2f} ms")

        benchmark_results[model_name] = {
            "ndcg_at_5": avg_ndcg,
            "mrr": avg_mrr,
            "precision_at_3": avg_p3,
            "latency_ms": avg_latency,
            "load_time_sec": load_time_sec
        }

    return benchmark_results


if __name__ == "__main__":
    CANDIDATES = [
        "Xenova/ms-marco-MiniLM-L-6-v2",
        "BAAI/bge-reranker-base",
        "jinaai/jina-reranker-v2-base-multilingual"
    ]
    results = run_reranker_benchmark(CANDIDATES)
    with open("reranker_benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print("\nBenchmark saved to reranker_benchmark_results.json")
