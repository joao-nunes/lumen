# Evaluation set for redaction (spec 011)

`entries.jsonl` holds 210 synthetic journal notes in English, European Portuguese and the two mixed, each with the identifiers that must be replaced and the decoys that must be kept. **Everything here is invented. This repository is public, so no real journal text ever goes in it.** Emails, URLs and IP addresses use the reserved documentation domains and ranges (`example.com`, `192.0.2.0/24`, `198.51.100.0/24`); phone, NIF, IBAN and card numbers are made up, and NIFs and IBANs have valid check digits so they look real to the rules.

- `dev` (60 entries, 20 per language) is for tuning the prompt.
- `test` (150 entries, 50 per language) is held out. It was written and committed before any redaction prompt existed, and isn't looked at until the measurement (spec 011 §2.6).

## Labels

Each entry has:

- `identifiers`: each distinct identifier once, exactly as written, with its type (spec 011 §2.1). Every occurrence of it in the text must go. `"rule": true` marks a fixed-shape identifier the rules promise to catch on their own (emails, URLs, handles, IP addresses, phone numbers, NIFs, IBANs, Cartão de Cidadão numbers, Portuguese postcodes, runs of seven or more digits); missing one is a bug in the rules, not a model limitation.
- `decoys`: words that look like identifiers or carry the meaning, and must be kept: relationship words, emotions, medication, countries, generic roles, ages, weekdays and relative dates.

How the labels were drawn:

- **People:** the name only, not the title, so "Dr. Costa" is labelled `Costa`. Nicknames, lowercase and misspelt names count; a spelling variant is its own identifier ("Kathryn", "Katherine").
- **Organizations** include employers, schools, hospitals, clinics, shops, teams and helplines.
- **Places:** cities, towns and neighbourhoods. Countries are decoys.
- **Dates:** only dates personal to the writer (birthdays, anniversaries, deaths). Weekdays, months on their own and relative dates are decoys.
- **Roles:** a title that points to one person ("the only paediatric cardiologist in Exeter"). A generic role ("nurse", "manager") is a decoy.
- **Names of things:** pets, bands, podcasts.

**Hard cases on purpose:**
- names that are also words, with the word nearby in lowercase ("Joy … joy", "A Rosa … cor-de-rosa", "A Dores tem dores")
- "Benfica" as a club in one entry and a neighbourhood in another
- names inside possessives
- cities next to countries
- personal dates next to relative ones
- 12 distressing entries, which must still get valid output

Matching is case-sensitive when measuring, so "Joy" must go while "joy" stays.

## Rules-only check

`tests/privacy/test_eval_set.py` runs the rules over every entry with a detector that finds nothing. Each `rule` identifier must be gone, and every decoy must survive. It doesn't measure the model: that's `make eval-redaction`, in the second implementation PR.

## Marking the blind sheet

`blind_sheet.csv` has 30 held-out entries, 10 per language, without their labels. The distressing entries are left out.

1. Copy it to `owner_identifiers.csv`.
2. For each note, list in the `identifiers` column everything you would replace before a hosted model saw it, separated by `;`, exactly as written.
3. Don't look at `entries.jsonl` while you do this. Your first reading is what's useful.

The agreement with the labels is reported with the measurement. Disagreement isn't a mistake: it shows how fuzzy the line is, especially for distinctive titles and personal dates.
