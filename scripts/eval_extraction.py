"""Measures a local model on the evaluation set (spec 006 §3). The entries are synthetic.

make eval-extraction MODEL=qwen3:8b                 # the tuning split, with its misses
make eval-extraction MODEL=qwen3:8b SPLIT=test      # the held-out split, metrics only
uv run python scripts/eval_extraction.py --agreement  # the owner's blind scores vs the labels
"""

import argparse
import time
from dataclasses import asdict
from pathlib import Path

from lumen.config import get_settings
from lumen.domain.dimensions import Dimension
from lumen.suggestions.evaluation import (
    Metrics,
    Outcome,
    agreement,
    blind_sheet_entries,
    load_entries,
    measure,
    meets_bar,
    read_blind_sheet,
    write_blind_sheet,
)
from lumen.suggestions.model import STARTER_TAGS, SuggestionsUnavailableError
from lumen.suggestions.ollama import OllamaSuggestionModel

FOLDER = Path(__file__).parents[1] / "evals" / "extraction"
ENTRIES, SHEET, SCORED = (
    FOLDER / "entries.jsonl",
    FOLDER / "blind_sheet.csv",
    FOLDER / "owner_scores.csv",
)


def report(language: str, metrics: Metrics) -> None:
    print(f"\n{language}: {'MEETS THE BAR' if meets_bar(metrics) else 'below the bar'}")
    print(f"  within one point   {metrics.within_one:6.1%}  of {metrics.addressed}  (bar: >= 95%)")
    print(
        f"  left blank         {metrics.left_blank:6.1%}  of {metrics.unaddressed}  (bar: >= 95%)"
    )
    print(f"  off by 3 or more   {metrics.off_by_three:6.1%}  (bar: <= 1%)")
    print(f"  95th pct seconds   {metrics.p95_seconds:6.1f}  (bar: < 10)")
    print(f"  failed calls       {metrics.failures:6d}")
    print(f"  failed on distress {metrics.distress_failures:6d}  (bar: 0)")
    print(f"  exact match        {metrics.exact:6.1%}")
    print(f"  tag precision      {metrics.tag_precision:6.1%}")
    print(f"  tag recall         {metrics.tag_recall:6.1%}")


def show_misses(outcomes: list[Outcome]) -> None:
    for outcome in outcomes:
        entry, suggestion = outcome.entry, outcome.suggestion
        if suggestion is None:
            print(f"{entry.id} FAILED")
            continue
        wrong = []
        for dimension in Dimension:
            label, guess = entry.scores.get(dimension), suggestion.scores.get(dimension)
            if dimension in entry.either or label == guess:
                continue
            if label is None or guess is None or abs(label - guess) > 1:
                wrong.append(f"{dimension.value}: {label} -> {guess}")
        if wrong or suggestion.tags != entry.tags:
            extra = sorted(suggestion.tags - entry.tags)
            missing = sorted(entry.tags - suggestion.tags)
            print(f"{entry.id} {wrong} tags +{extra} -{missing}\n    {entry.text}")


def evaluate(model_name: str, split: str, misses: bool) -> None:
    url = get_settings().ollama_url
    model = OllamaSuggestionModel(url, model_name, timeout_seconds=120)
    outcomes: list[Outcome] = []
    for entry in [e for e in load_entries(ENTRIES) if e.split == split]:
        started = time.perf_counter()
        try:
            suggestion = model.suggest(entry.text, tuple(Dimension), STARTER_TAGS)
        except SuggestionsUnavailableError:
            suggestion = None
        outcomes.append(Outcome(entry, suggestion, time.perf_counter() - started))

    print(f"{model_name}, {split} split")
    for language in ("en", "pt"):
        report(language, measure([o for o in outcomes if o.entry.language == language]))
    if misses:
        print("\nMisses:")
        show_misses(outcomes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--write-sheet", action="store_true")
    parser.add_argument("--agreement", action="store_true")
    args = parser.parse_args()

    if args.write_sheet:
        write_blind_sheet(blind_sheet_entries(load_entries(ENTRIES)), SHEET)
    elif args.agreement:
        chosen = blind_sheet_entries(load_entries(ENTRIES))
        print(asdict(agreement(chosen, read_blind_sheet(SCORED))))
    else:
        # Misses are for tuning: reading the held-out ones would make them tuning data too.
        evaluate(args.model, args.split, misses=args.split == "dev")


if __name__ == "__main__":
    main()
