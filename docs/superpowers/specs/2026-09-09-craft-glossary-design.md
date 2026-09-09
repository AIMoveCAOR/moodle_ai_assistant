# Per-craft French glossary for translation

**Date:** 2026-09-09
**Status:** approved (user delegated the remaining decisions)

## Problem

Course content is translated to French at ingest time and the French text is
what gets embedded, so a wrong French word is not a cosmetic flaw — it is the
text retrieval actually searches. Three rounds of prompt tuning each fixed the
bug they named and surfaced another:

1. Heading translation without context produced wrong headings
   (`Ανόπτηση` → *Décapage*, pickling, instead of *Recuisson*, annealing).
   Fixed in PR #26 by giving the heading translator surrounding context.
2. English words survived translation (`annealing`, `annealer`).
   Fixed in PR #27 by forbidding English terms in the prompt.
3. The model still picks French words that are not the trade's words.

Prompt tuning has no clean endpoint because each instruction only forbids the
error it was written for. A glossary fixes the class instead of the instance:
it tells the model which French word belongs to which concept in this craft.

## Evidence

Mined from the live corpus (read from a copy of `chroma.sqlite3`, never the
live file). What the corpus actually contains was itself a finding:

| Course | Chunks | Source | Nature |
|---|---|---|---|
| 101 | 178 | **not translated** | human-authored French, CERFAV lampworking |
| 109 | 53 | Greek | machine-translated furnace glassblowing |
| 98 | 9 | English | machine-translated, museum glassblowing |
| everything else | ~11,400 | mostly English | **AI/robotics master's programme** |

Two consequences:

- The corpus is overwhelmingly **not craft content** — it is lecture material on
  image classification, motion capture and automated vehicles. Applying trade
  vocabulary there would be a defect, so the glossary must default to nothing
  and apply only where a craft is positively resolved.
- Course 101 was never machine-translated, so its wording is a French
  professional's. It is the authoritative source for the term list, and the
  machine output in 98 and 109 is what gets audited against it.

Confirmed defects in the machine-translated French:

| Found | Should be | Note |
|---|---|---|
| `cullet` ×4 | `calcin` | English survived PR #27's instruction |
| `fuso` ×5 | `canne` | not a French word at all; the blowpipe |
| `souffle-canneau` ×2 | `canne` | invented compound; the blowpipe |
| `L'anneau de recuisson` ×3 | `arche de recuisson` | *anneau* is a ring; the text itself calls it "un four" |
| `glace incandescente` | `verre incandescent` | **glace is ice**; a serious mistranslation |
| `éclats de glace froide` | `éclats de verre froid` | same defect |
| `recuit` ×3 vs `recuisson` ×24 | `recuisson` | inconsistent; course 101 uses *recuisson* |

`tesselles` and `aide-couvreur` are suspect but not certain and are left out
pending review. `tube de soufflage` is left alone deliberately: it appears once
in the human French of course 101, where the craft is lampworking and the tube
really is a glass tube rather than a furnace canne.

## Decisions

1. **French-only term lists, not source→French pairs.** One list per craft
   serves all twelve source languages in the corpus. The observed defects are
   the model choosing a wrong French word, not misreading the source, so pairs
   would buy precision the defects do not call for while multiplying
   maintenance by the number of languages.

2. **Each entry carries a short French gloss.** A bare word list would not have
   fixed `cullet` or `glace`: the model needs to know *which concept* a term
   names before it can choose it. `calcin — fragments de verre déjà fabriqué
   réintroduits dans le mélange` is actionable; `calcin` alone is not.

3. **A Python module in the repo**, `config/glossaries.py`, in the style of
   `DOMAIN_MAP` and the refusal-message table beside it. No new dependency, no
   parse-error path, and the exact vocabulary behind any ingest is recorded in
   git history — which matters because the glossary changes what gets embedded.

4. **Glovemaking ships with an empty list.** Category 34 has no ingested
   content, so there is nothing to mine and nothing to verify. The key exists
   with a comment; adding terms is a one-line change. Inventing terms would
   reproduce exactly the guessing this design replaces.

5. **Craft resolution is a lookup, never a guess.** Unknown craft means no
   glossary and today's behaviour, unchanged.

## Design

### `config/crafts.py` (new, neutral)

`DOMAIN_MAP` moves here from `services/rag_service.py`, which re-exports it so
existing importers keep working. The move exists because ingest needs the map
and `services/course_rag_service.py` must not import `services/rag_service.py`
— that would pull the whole RAG stack (sentence_transformers, langsmith) into
the ingest path and set up a cycle the translation layer documents avoiding.

```python
def resolve_craft_for_course(course_id, silo_service) -> Optional[str]
```

Walks `DOMAIN_MAP`, asks `silo_service.get_course_ids_by_category` for each
category, returns the matching craft or `None`. `get_course_ids_by_category`
already has a TTL cache, so repeated calls during a re-ingest are cheap.
Any exception returns `None` — a database hiccup must degrade to "no
glossary", never fail the ingest.

### `config/glossaries.py` (new)

```python
CRAFT_GLOSSARIES: Dict[str, Dict[str, str]]   # craft -> {term: gloss}

def glossary_prompt_fragment(craft: Optional[str]) -> str
```

Returns `""` for an unknown craft or an empty list, so every call site can
concatenate unconditionally and a missing craft costs nothing. Otherwise it
returns a short French block naming the terms and their meanings.

### Call sites

| Site | How the craft is known |
|---|---|
| `course_rag_service` heading prompt (:593) | resolved from `course_id`, cached per course |
| `course_rag_service` body prompts (:649, :763) | same |
| `annotation_service` (:224) | already on the annotation record |
| `rag_service.detect_and_translate_query` (:1678) | `DOMAIN_MAP.get(state["selected_domain"])`, the idiom already used at :1793 and :1927 |

`CourseRAGService.__init__` gains an optional `silo_service`, injected at
`pipeline.py:120` alongside the services already wired there. Optional because
`eval/10_cross_lingual_corpus_eval.py` constructs the service directly and must
keep working without a database.

`translation_service.build_chunk_translation_prompt` gains a `glossary=""`
keyword argument; `course_rag_service._build_heading_translation_prompt` gains
the same. Both default to today's exact prompt when empty.

### Error handling

Every failure degrades to "no glossary": unknown craft, database error,
unmapped course, empty term list. The glossary can improve a translation and
can never prevent one.

### Testing

- `glossary_prompt_fragment` returns `""` for `None`, for an unknown craft, and
  for a craft whose list is empty.
- The fragment names every term for a craft that has them.
- `resolve_craft_for_course` returns the craft for a mapped course, `None` for
  an unmapped one, and `None` when the silo service raises.
- The chunk and heading prompts are byte-identical to today's when no glossary
  is passed, and contain the terms when one is.
- `DOMAIN_MAP` re-exported from `services.rag_service` is the same object as
  `config.crafts.DOMAIN_MAP`.

## Out of scope

- The full corpus re-ingest that makes the glossary take effect. It is ~10
  hours and is held for the user.
- Populating the glovemaking list.
- The `tesselles` / `aide-couvreur` judgements, which need a glassblower.
