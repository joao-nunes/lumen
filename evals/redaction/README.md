# Evaluation set for redaction (spec 011)

`entries.jsonl` holds 690 synthetic journal notes in English, European Portuguese and the two mixed, each with the identifiers that must be replaced and the decoys that must be kept. **Everything here is invented. This repository is public, so no real journal text ever goes in it.** Emails, URLs and IP addresses use the reserved documentation domains and ranges (`example.com`, `example.org`, `example.net`, `192.0.2.0/24`, `198.51.100.0/24`); phone, NIF, IBAN and card numbers are made up so that none can belong to anyone, while still having the shape the rules catch:

- **NIFs** have a valid check digit but start with 0, which no category of NIF holder uses.
- **Portuguese phone numbers** start with 97, which is neither a mobile range (91, 92, 93, 96) nor a landline (2). It's unassigned rather than reserved, so if ANACOM ever opens it, they could become real. **UK phone numbers** are in Ofcom's ranges for drama.
- **Portuguese IBANs** pass the IBAN check but have bank code 0000 and a wrong NIB check digit, so no account can have them. **UK IBANs** are the official examples.
- **Other IDs:** the SNS number starts with 0, with a wrong NIF check digit, and the car plate (`12-KW-34`) uses letters Portugal didn't use in that format.
- **Cartão de Cidadão numbers** have wrong check digits, and **card numbers** fail the Luhn check.
- **Other references** (deposits, council tax, bookings) are 8 digits in two groups of four, starting with `00`: no real scheme is implied, and the leading `00` keeps them clear of phone numbers and NIFs. The rules catch them as runs of seven or more digits.

- `dev` (90 entries, 30 per language) is for tuning the prompt. Its last 10 per language (`*-dev-21` to `-30`) were added for `redaction_v3` (spec 011 §8.4): they're rich in titles and personal dates, and carry decoys of both kinds below.
- `test` (150 entries, 50 per language, `*-test-v3-01` to `-50`) is held out for `redaction_v3`. It was written and committed before that prompt existed, each language on its own, with its own stories, names and kinds of titles and events rather than translations. Each language has 20 titles, 19 or 20 personal dates and 161 to 165 direct identifiers, with posts many people share at a named institution and dates of private events as decoys.
- **Titles and real places.** A title is meant to point to someone who doesn't exist. The towns and institutions in `test`'s titles were checked with a web search (2026-11-27), and the nine that turned out to be real or close to something real were renamed before the split was committed (spec 011 §10). Places outside titles, such as Penrith or Braga, may be real.
- `test_v2` (225 entries, 75 per language) held `redaction_v2`'s measurement (spec 011 §10). Its first 150 entries (`*-test-v2-01` to `-50`) were written and committed before that prompt existed. The other 75 (`-51` to `-75`) were added after the first measurement, at the owner's request: each language's 25 were written on their own, and they're rich in personal dates and titles. A web search (2026-11-20) found none of those 75 entries' title towns and institutions; the first 150 entries' weren't checked, and some Portuguese ones are real places (such as Vilar Seco, Souto Maior, Vale Formoso and Penaverde). Those stories are invented, and nothing in them is about a real person. Its title labels were aligned to the rules below in 2026-11; its date labels follow the broader rule it was measured under. It's never tuned on or measured against again.
- `test_v1` (225 entries, 75 per language) held `redaction_v1`'s measurement. Its results have been read, so it's never tuned on or measured against again. It keeps the 30 entries on the blind sheet, and the owner's marks for them.

## Labels

Each entry has:

- `identifiers`: each distinct identifier once, exactly as written, with its type (spec 011 §2.1). Every occurrence of it in the text must go. `"rule": true` marks a fixed-shape identifier the rules promise to catch on their own (emails, URLs, handles, IP addresses, phone numbers, NIFs, IBANs, Cartão de Cidadão numbers, Portuguese postcodes, runs of seven or more digits); missing one is a bug in the rules, not a model limitation.
- `decoys`: words that look like identifiers or carry the meaning, and must be kept: relationship words, emotions, medication, countries, generic roles, ages, weekdays and relative dates.

How the labels were drawn:

- **People:** the name only, not the title, so "Dr. Costa" is labelled `Costa`. Nicknames, lowercase and misspelt names count; a spelling variant is its own identifier ("Kathryn", "Katherine").
- **Organizations** include employers, schools, hospitals, clinics, shops, teams and helplines: places a person goes to or deals with. The brand of something a person owns, such as a car ("his old Renault"), is a decoy.
- **Places:** cities, towns, neighbourhoods and regions within a country ("o Minho"). Countries are decoys.
- **Dates:** only dates of events on a record others can see, or would know about (spec 011 §8.4): births and birthdays, deaths and funerals, weddings, civil unions and their anniversaries, divorces, accidents or crimes that could make the news, court hearings, and ceremonies that are announced or recorded, such as engagements, christenings, graduations, thesis defences and retirements. Dates of private events are decoys: surgeries, treatments, diagnoses, moves, first dates, appointments, a job's start, "our anniversary" with no sign that it's a wedding or a civil union, an accident with no sign it was public, and an ordination, which rule 3 doesn't list. Weekdays, months on their own and relative dates are decoys too. `test_v2` and `test_v1` keep their own, broader rule.
- **Roles:** a post one person holds at a named institution or place at a time ("the vicar of St Aldhelm's", "a diretora do Lar de São Romão"), or a unique title ("the only paediatric cardiologist in Exeter"). The label is the title word only (spec 011 §8.4):
  - an institution or place in it is labelled on its own, as `ORG` or `PLACE`, so "the clinical director of the Hospital de Faro" gives `clinical director` and `Hospital de Faro`;
  - generic words for the body it belongs to stay out ("presidente da junta" is `presidente`), and so does a department or subject the post heads ("the head of maths" is `head`);
  - a unique title drops its qualifier and the traits that make it unique, while its specialty stays: "the only Italian-speaking GP" is `GP`, "the first deaf head teacher" `head teacher`.

  A post many people share there ("a nurse at Hospital X", "my GP at Y Surgery") and a generic role ("nurse", "manager") are decoys. A rank or form of address before a name ("Wing Commander Hale", "o cónego Valério") is neither labelled nor a decoy.
- **Names of things:** pets, bands, podcasts.

**Hard cases on purpose:**
- names that are also words, with the word nearby in lowercase ("Joy … joy", "A Rosa … cor-de-rosa", "A Dores tem dores")
- "Benfica" as a club in one entry and a neighbourhood in another
- names inside possessives
- cities next to countries
- personal dates next to relative ones
- 36 distressing entries (9 of them in the held-out `test` split), which must still get valid output

Matching is case-sensitive when measuring, so "Joy" must go while "joy" stays.

## Rules-only check

`tests/privacy/test_eval_set.py` runs the rules over every entry with a detector that finds nothing. Each `rule` identifier must be gone, and every decoy must survive. It doesn't measure the model: that's `make eval-redaction`, in the second implementation PR.

## Marking the blind sheet

`blind_sheet.csv` has 30 held-out entries, 10 per language, without their labels. The distressing entries are left out.

1. Copy it to `owner_identifiers.csv`.
2. For each note, list in the `identifiers` column everything you would replace before a hosted model saw it, separated by `;`, exactly as written.
3. Don't look at `entries.jsonl` while you do this. Your first reading is what's useful.

The owner's marking is in `owner_identifiers.csv`, done on 2026-11-19, before any redaction prompt existed. The agreement with the labels is reported with the measurement. Disagreement isn't a mistake: it shows how fuzzy the line is, especially for distinctive titles and personal dates.
