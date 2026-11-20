"""Measures redaction with a local model on the evaluation set (spec 011 §2.6).

The entries are synthetic.

make eval-redaction MODEL=gemma4:26b                # the tuning split, with its misses
make eval-redaction MODEL=gemma4:26b SPLIT=test     # the held-out split, metrics only
uv run python scripts/eval_redaction.py --agreement  # the owner's blind marks vs the labels

Every run's output, entry by entry, is saved in evals/redaction/runs/ (not committed).
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from lumen.config import get_settings
from lumen.privacy.evaluation import (
    CONTEXTUAL_BAR,
    DECOYS_BAR,
    DIRECT_BAR,
    LANGUAGES,
    P95_SECONDS_BAR,
    Metrics,
    Outcome,
    agreement,
    caught,
    collect,
    decoy_kept,
    load_entries,
    measure,
    meets_bar,
    read_owner_sheet,
    record_if_met,
)
from lumen.privacy.ollama import PROMPT_NAME, OllamaDetector, prompt_fingerprint
from lumen.privacy.redaction import Redactor

FOLDER = Path(__file__).parents[1] / "evals" / "redaction"
ENTRIES, MARKED, MEASURED = (
    FOLDER / "entries.jsonl",
    FOLDER / "owner_identifiers.csv",
    FOLDER / "measured_prompt.json",
)
RUNS = FOLDER / "runs"


def report(language: str, m: Metrics) -> None:
    print(f"\n{language}: {'MEETS THE BAR' if meets_bar(m) else 'below the bar'}")
    print(
        f"  direct recall, of {m.direct:<4}     {m.direct_recall:6.1%}  (bar: >= {DIRECT_BAR:.0%})"
    )
    print(
        f"  contextual recall, of {m.contextual:<4} {m.contextual_recall:6.1%}"
        f"  (bar: >= {CONTEXTUAL_BAR:.0%})"
    )
    print(f"  decoys kept, of {m.decoys:<4}       {m.decoys_kept:6.1%}  (bar: >= {DECOYS_BAR:.0%})")
    print(f"  95th pct seconds          {m.p95_seconds:6.1f}  (bar: < {P95_SECONDS_BAR:.0f})")
    print(f"  failed entries            {m.failures:6d}")
    print(f"  failed on distress        {m.distress_failures:6d}  (bar: 0)")
    print(f"  leak-free entries         {m.leak_free:6.1%}")
    print(f"  right type, of caught     {m.right_type:6.1%}")


def show_misses(outcomes: list[Outcome]) -> None:
    for outcome in outcomes:
        entry, result = outcome.entry, outcome.result
        if result is None:
            print(f"{entry.id} FAILED")
            continue
        missed = [
            f"{i.text} ({i.type})" for i in entry.identifiers if not caught(i, entry, result.text)
        ]
        lost = [d for d in entry.decoys if not decoy_kept(d, entry, result.text)]
        if missed or lost:
            print(f"{entry.id} missed {missed} lost {lost}\n    {result.text}")


def save(outcomes: list[Outcome], *, model_name: str, split: str, fingerprint: str) -> Path:
    """Keeps each entry's output, so later questions about a run need no bounds or reruns."""
    RUNS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = RUNS / f"{stamp}-{split}-{model_name.replace(':', '_')}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for o in outcomes:
            entry, result = o.entry, o.result
            row = {
                "id": entry.id,
                "prompt": PROMPT_NAME,
                "sha256": fingerprint,
                "seconds": round(o.seconds, 3),
                "loads_model": o.loads_model,
                "output": None if result is None else result.text,
                "missed": None
                if result is None
                else [i.text for i in entry.identifiers if not caught(i, entry, result.text)],
                "lost": None
                if result is None
                else [d for d in entry.decoys if not decoy_kept(d, entry, result.text)],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def evaluate(model_name: str, split: str, misses: bool) -> None:
    # The app's own timeout: a slower reply fails closed there, so it fails here too.
    detector = OllamaDetector(get_settings().ollama_url, model_name)
    entries = [e for e in load_entries(ENTRIES) if e.split == split]
    outcomes = collect(Redactor(detector), entries)

    fingerprint = prompt_fingerprint()
    saved = save(outcomes, model_name=model_name, split=split, fingerprint=fingerprint)
    print(f"{model_name}, {split} split, {PROMPT_NAME} ({fingerprint[:12]})")
    by_language = {
        language: measure([o for o in outcomes if o.entry.language == language])
        for language in LANGUAGES
    }
    for language, metrics in by_language.items():
        report(language, metrics)
    if record_if_met(
        MEASURED,
        prompt=PROMPT_NAME,
        sha256=fingerprint,
        model=model_name,
        split=split,
        by_language=by_language,
    ):
        print(f"\nRecorded in {MEASURED.name}")
    print(f"\nEach entry's output is in {saved.relative_to(FOLDER.parents[1])}")
    if misses:
        print("\nMisses:")
        show_misses(outcomes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--agreement", action="store_true")
    args = parser.parse_args()

    if args.agreement:
        result = agreement(load_entries(ENTRIES), read_owner_sheet(MARKED))
        print(
            f"labelled {result.labelled}, marked by the owner {result.marked}, both {result.both}"
            f"\n  of the labels, the owner marked {result.both / result.labelled:.1%}"
            f"\n  of the owner's marks, labelled  {result.both / result.marked:.1%}"
        )
    else:
        # Misses are for tuning: reading the held-out ones would make them tuning data too.
        evaluate(args.model, args.split, misses=args.split == "dev")


if __name__ == "__main__":
    main()
