# Evaluation set for redaction (spec 011)

`entries.jsonl` holds 435 synthetic journal notes in English, European Portuguese and the two mixed, each with the identifiers that must be replaced and the decoys that must be kept. **Everything here is invented. This repository is public, so no real journal text ever goes in it.** Emails, URLs and IP addresses use the reserved documentation domains and ranges (`example.com`, `example.org`, `example.net`, `192.0.2.0/24`, `198.51.100.0/24`); phone, NIF, IBAN and card numbers are made up so that none can belong to anyone, while still having the shape the rules catch:

- **NIFs** have a valid check digit but start with 0, which no category of NIF holder uses.
- **Portuguese phone numbers** start with 97, which is neither a mobile range (91, 92, 93, 96) nor a landline (2). It's unassigned rather than reserved, so if ANACOM ever opens it, they could become real. **UK phone numbers** are in Ofcom's ranges for drama.
- **Portuguese IBANs** pass the IBAN check but have bank code 0000 and a wrong NIB check digit, so no account can have them. **UK IBANs** are the official examples.
- **Other IDs:** the SNS number starts with 0, with a wrong NIF check digit, and the car plate (`12-KW-34`) uses letters Portugal didn't use in that format.
- **Cartão de Cidadão numbers** have wrong check digits, and **card numbers** fail the Luhn check.

- `dev` (60 entries, 20 per language) is for tuning the prompt.
- `test` (150 entries, 50 per language) is held out for `redaction_v2`. It was written and committed before that prompt existed, and isn't looked at until its measurement (spec 011 §10). Its titles name invented towns and institutions, so no story is about a real office holder.
- `test_v1` (225 entries, 75 per language) held `redaction_v1`'s measurement. Its results have been read, so it's never tuned on or measured against again. It keeps the 30 entries on the blind sheet, and the owner's marks for them.

## Labels

Each entry has:

- `identifiers`: each distinct identifier once, exactly as written, with its type (spec 011 §2.1). Every occurrence of it in the text must go. `"rule": true` marks a fixed-shape identifier the rules promise to catch on their own (emails, URLs, handles, IP addresses, phone numbers, NIFs, IBANs, Cartão de Cidadão numbers, Portuguese postcodes, runs of seven or more digits); missing one is a bug in the rules, not a model limitation.
- `decoys`: words that look like identifiers or carry the meaning, and must be kept: relationship words, emotions, medication, countries, generic roles, ages, weekdays and relative dates.

How the labels were drawn:

- **People:** the name only, not the title, so "Dr. Costa" is labelled `Costa`. Nicknames, lowercase and misspelt names count; a spelling variant is its own identifier ("Kathryn", "Katherine").
- **Organizations** include employers, schools, hospitals, clinics, shops, teams and helplines.
- **Places:** cities, towns and neighbourhoods. Countries are decoys.
- **Dates:** only dates personal to the writer (birthdays, anniversaries, deaths). Weekdays, months on their own and relative dates are decoys.
- **Roles:** a title that points to one person ("the only paediatric cardiologist in Exeter"). The title alone is the `ROLE`; an institution or place in it is labelled on its own, as `ORG` or `PLACE`, so "the clinical director of the Hospital de Faro" gives `clinical director` and `Hospital de Faro`. A generic role ("nurse", "manager") is a decoy.
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

The owner's marking is in `owner_identifiers.csv`, done on 2026-11-19, before any redaction prompt existed. The agreement with the labels is reported with the measurement. Disagreement isn't a mistake: it shows how fuzzy the line is, especially for distinctive titles and personal dates.
