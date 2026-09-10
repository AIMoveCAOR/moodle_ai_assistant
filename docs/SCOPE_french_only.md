# Scope — CraftPilot is French-only

**Decided 2026-09-10 by the project owner.** All course content for this
project will be in French. Work on making retrieval function across other
source languages is stopped, not paused: do not restart it without a new
decision recorded here.

This file exists because the multilingual work was *nearly* good, which is the
most expensive kind of unfinished. Someone reading the code will find a
translation pipeline, a per-craft glossary and a heading translator, all
plausible and all now dormant. Here is what to leave alone and why.

---

## What the machinery was for

Course pages were translated to French at ingest time and the **French text was
what got embedded**, so retrieval searched the translation, not the original.
That made translation quality a retrieval concern rather than a cosmetic one,
and it is why so much effort went into it (PRs #26–#28 and the
`feat/craft-glossary` branch).

With French-only content, none of that runs. French text is never translated,
so the translator, the glossary and the heading translator sit idle.

## The one thing that could still damage French

Idle is not the same as harmless. The pipeline decides whether to translate by
asking py3langid what language a chunk is in, and py3langid is confidently
wrong often enough to matter. It reads this paragraph from course 101 — human
written French, a table of thermal expansion coefficients —

```
LES 4 FAMILLES DE VERRE ESSENTIELLES > PROPRIÉTÉS PHYSIQUES FONDAMENTALES >
Dilatation Thermique > Classement par coefficient (du plus grand au plus petit) :
Cristal : 92-96 × 10⁻⁷/°C  Sodo-calcique : 85-90 × 10⁻⁷/°C  ...
```

as **Latin, with confidence 1.0000, and French at 0.0000**.

The old guard in `decide_translation` was "translate unless confidence is low",
which assumes a wrong answer arrives hesitantly. This one does not, so the
chunk was sent to the LLM and round-tripped French → French. Measured over the
whole of course 101, the only human-authored French course in the corpus: **1
chunk in 179**. It survived unaltered because it is mostly digits. There is no
reason to expect the next one to.

**The guard is now an allowlist**
(`services/translation_service.TRANSLATABLE_SOURCE_LANGUAGES`, currently
`{"en"}`). A language outside it is treated as a misdetection and the text is
left alone. Being wrong now means doing nothing, which is safe by construction:
the text is already in the language it is in.

Verified after the change, replaying the real detector over stored chunks:

| Course | Content | Would be translated |
|---|---|---|
| 101 | human-written French, 179 chunks | 1 → **0** |
| 109 | Greek test course, 53 chunks | 53 → **0** |

`tests/test_translation_service.py` pins this with the actual course-101
paragraph and the real identifier, not a mock — a mock would only have agreed
with whatever we already believed.

## The allowlist also narrows the query path — on purpose

`decide_translation` is shared by four callers, and only two of them are
ingest. The other two are learner-facing, in `services/rag_service.py`:

- `detect_and_translate_query` translates an incoming question into French
  before retrieval, because the index and the PRF prompts are French;
- `detect_query_language` picks the language a refusal is written in.

The gates were deliberately built to agree ("uses exactly the same thresholds
… so the two never disagree"), so the allowlist applies to queries too. Two
consequences, both accepted:

- **A question asked in French can no longer be mangled** by a needless
  French → French round trip when langid misreads it. This is a gain, and the
  same failure the ingest guard was written for.
- **A question asked in a language other than French or English is no longer
  translated or answered in that language.** A Greek learner who used to get a
  Greek refusal now gets a French one, and their Greek question is searched
  as-is against a French index. This is a real narrowing of behaviour. It is
  in scope to lose — it is exactly the cross-language support this decision
  stops — but it is the one change here a user could notice, so it is written
  down rather than left to be discovered.

Reverting just this part means passing the allowlist only from the two ingest
callers and leaving the query path on the old gate. That reintroduces the
divergence the shared helper was created to prevent, so do it knowingly.

## Deliberately not done

- **The full corpus re-ingest (~10 h, ~7 M tokens, 8,970 translatable chunks).**
  Its entire purpose was to re-translate non-French content with better
  prompts. See `RUNBOOK_reingest.md`, now marked suspended.
- **Extending the glossary past glassblowing.** `config/glossaries.py` keeps
  the terms already gathered; nothing more is being added.

## Known defects left standing, in translated content only

Found in the 2026-09-10 course-109 audit, **after** the glossary shipped.
Recorded so nobody rediscovers them as new, and left unfixed because they can
only affect non-French source content, which is now out of scope:

- **The glossary contaminates short headings.** The glossary block opens with
  the words "Vocabulaire du métier", and for an input as short as a section
  title it dominates the prompt. Three of eight module headings in course 109
  had their topic word replaced by "Vocabulaire": `Τα εργαλεία του υαλουργού`
  ("the glassblower's tools") became *Vocabulaire du verrier*, and `Φύσημα και
  σχηματισμός` ("blowing and forming") became *Vocabulaire et mise en forme*.
  Introduced by commit af48e25, which passed the glossary to the heading
  translator to fix a real breadcrumb/body term mismatch. Both states have
  defects; neither was worth another pilot once the scope changed. If
  translation is ever revived, **start here**, and note that the breadcrumb is
  embedded with every chunk of its page, so a bad heading poisons the vectors.
- **A transliterated heading.** `Ανόπτηση` (annealing) came back as *Anôpsée*,
  an invented word, in module 1298 — despite the prompt forbidding
  transliteration.

## The rest of the corpus

Roughly 8,000 chunks of English AI/robotics coursework remain indexed as
French translations from earlier runs. They are untouched and keep working.
English stays in the allowlist for that reason: it is the one non-French
language present in bulk and the one py3langid identifies dependably.

## If this decision reverses

Re-read this file first, then the glossary defect above. Widening
`TRANSLATABLE_SOURCE_LANGUAGES` is the single switch that turns the pipeline
back on — and doing so re-exposes French to misdetection, so keep the
course-101 regression test green.
