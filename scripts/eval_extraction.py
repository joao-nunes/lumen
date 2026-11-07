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
    Entry,
    Metrics,
    Outcome,
    agreement,
    blind_sheet_entries,
    labelled_by_owner,
    load_entries,
    measure,
    meets_bar,
    read_blind_sheet,
    record_if_met,
    write_blind_sheet,
)
from lumen.suggestions.model import STARTER_TAGS, SuggestionsUnavailableError
from lumen.suggestions.ollama import OllamaSuggestionModel
from lumen.suggestions.prompt import PROMPT_NAME, prompt_fingerprint

FOLDER = Path(__file__).parents[1] / "evals" / "extraction"
ENTRIES, SHEET, SCORED, MEASURED = (
    FOLDER / "entries.jsonl",
    FOLDER / "blind_sheet.csv",
    FOLDER / "owner_scores.csv",
    FOLDER / "measured_prompt.json",
)


def report(language: str, metrics: Metrics) -> None:
    print(f"\n{language}: {'MEETS THE BAR' if meets_bar(metrics) else 'below the bar'}")
    print(f"  within one (of suggested) {metrics.within_one:6.1%}  (bar: >= 95%)")
    print(f"  coverage of {metrics.addressed:<4} addressed {metrics.coverage:6.1%}  (bar: >= 75%)")
    print(
        f"  left blank of {metrics.unaddressed:<4}       {metrics.left_blank:6.1%}  (bar: >= 90%)"
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


def run(model: OllamaSuggestionModel, entries: list[Entry]) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for entry in entries:
        started = time.perf_counter()
        try:
            suggestion = model.suggest(entry.text, tuple(Dimension), STARTER_TAGS)
        except SuggestionsUnavailableError:
            suggestion = None
        outcomes.append(Outcome(entry, suggestion, time.perf_counter() - started))
    return outcomes


def evaluate(model_name: str, split: str, misses: bool) -> None:
    url = get_settings().ollama_url
    model = OllamaSuggestionModel(url, model_name, timeout_seconds=120)
    outcomes = run(model, [e for e in load_entries(ENTRIES) if e.split == split])

    fingerprint = prompt_fingerprint()
    print(f"{model_name}, {split} split, {PROMPT_NAME} ({fingerprint[:12]})")
    english, portuguese = (
        measure([o for o in outcomes if o.entry.language == language]) for language in ("en", "pt")
    )
    report("en", english)
    report("pt", portuguese)
    if record_if_met(
        MEASURED,
        prompt=PROMPT_NAME,
        sha256=fingerprint,
        model=model_name,
        split=split,
        english=english,
        portuguese=portuguese,
    ):
        print(f"\nRecorded in {MEASURED.name}")
    if misses:
        print("\nMisses:")
        show_misses(outcomes)


def against_owner(model_name: str) -> None:
    """The model against the owner's blind scores, on the 30 notes they scored."""
    chosen = blind_sheet_entries(load_entries(ENTRIES))
    model = OllamaSuggestionModel(get_settings().ollama_url, model_name, timeout_seconds=120)
    print(f"{model_name}, against the owner's blind scores")
    for language in ("en", "pt"):
        entries = [e for e in chosen if e.language == language]
        report(language, measure(run(model, labelled_by_owner(entries, read_blind_sheet(SCORED)))))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--write-sheet", action="store_true")
    parser.add_argument("--agreement", action="store_true")
    parser.add_argument("--against-owner", action="store_true")
    args = parser.parse_args()

    if args.write_sheet:
        write_blind_sheet(blind_sheet_entries(load_entries(ENTRIES)), SHEET)
    elif args.agreement:
        chosen = blind_sheet_entries(load_entries(ENTRIES))
        print(asdict(agreement(chosen, read_blind_sheet(SCORED))))
    elif args.against_owner:
        against_owner(args.model)
    else:
        # Misses are for tuning: reading the held-out ones would make them tuning data too.
        evaluate(args.model, args.split, misses=args.split == "dev")


if __name__ == "__main__":
    main()
