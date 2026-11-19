"""Benchmark: run the pipeline on the sample document and compare with expected labels.
Usage:  python -m scripts.benchmark            (uses the free LLM if configured)
        python -m scripts.benchmark --no-llm   (offline rules only)
Writes docs/benchmark_results.md - paste the numbers into the README."""
import json
import sys
from collections import Counter
from pathlib import Path

from src.pipeline import run_pipeline

ROOT = Path(__file__).resolve().parent.parent


def main():
    use_llm = "--no-llm" not in sys.argv
    text = (ROOT / "data/sample/sample_paper.txt").read_text(encoding="utf-8")
    expected = json.loads((ROOT / "data/sample/expected_labels.json").read_text())
    run = run_pipeline(text, "sample_paper.txt", use_llm=use_llm)
    rows, correct, confusion = [], 0, Counter()
    for e in expected:
        hit = next((r for r in run["results"] if e["claim_contains"] in r["claim"]), None)
        got = hit["status"] if hit else "NOT_EXTRACTED"
        ok = got in e["acceptable"]
        correct += ok
        confusion[(e["acceptable"][0], got)] += 1
        rows.append(f"| {e['claim_contains']} | {', '.join(e['acceptable'])} | {got} | {'PASS' if ok else 'FAIL'} |")
    acc = correct / len(expected)
    out = [f"# Benchmark ({'LLM' if use_llm else 'offline rules'})", "", f"Accuracy: **{correct}/{len(expected)} = {acc:.0%}**", "",
           "| Claim contains | Acceptable | Got | Result |", "|---|---|---|---|", *rows]
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs/benchmark_results.md").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
