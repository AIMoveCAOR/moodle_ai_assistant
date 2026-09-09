"""Per-craft French trade vocabulary, injected into every translation prompt.

Why this exists
---------------
Course content is translated to French at ingest time and the *French* text is
what gets embedded, so a wrong French word is not cosmetic — it is the text
retrieval searches. Three rounds of prompt tuning each fixed the error they
named and left the next one standing:

  * PR #26 gave the heading translator context, so `Ανόπτηση` stopped becoming
    *Décapage* (pickling) instead of *Recuisson* (annealing);
  * PR #27 forbade English words, so `annealing` and `annealer` disappeared;
  * and the model still reached for French words the trade does not use.

Forbidding errors one at a time has no endpoint. Naming the right word does:
this table tells the translator which French term belongs to which concept.

Why each term carries a gloss
-----------------------------
A bare word list would not have fixed `cullet`. The model has to recognise the
*concept* in the source text before it can pick the term, so each entry pairs
the term with what it means. The gloss is French because the whole prompt is.

Provenance, and what still needs a glassblower
----------------------------------------------
Terms are grouped by where they came from, because that determines how much to
trust them:

  ATTESTED  — used in course 101, whose 178 chunks were never machine-
              translated. That is a French professional's own wording (CERFAV
              lampworking material), so these are as authoritative as the
              corpus gets.
  CORRECTED — the machine translation produced something wrong and this is the
              proposed replacement. Each one names the defect it fixes. These
              are the entries a glassblower should check first.

Adding a craft
--------------
Add a key here matching the ``craft`` value in ``config.crafts.DOMAIN_MAP``.
An empty dict is a valid, deliberate state: it means the craft exists but
nobody has supplied its vocabulary yet, and translation then behaves exactly
as it does today. ``tests/test_craft_glossary.py`` fails if a craft in
DOMAIN_MAP has no key at all.
"""

from typing import Dict, Optional


CRAFT_GLOSSARIES: Dict[str, Dict[str, str]] = {
    "glassblowing": {
        # ── CORRECTED — each fixes a defect found in the ingested corpus ──
        #
        # Found as `fuso` (x5) and `souffle-canneau` (x2), neither of which is
        # French. The Greek source calls it "the metal tube through which the
        # artisan blows air", which is a canne.
        "la canne": "tube métallique creux par lequel le verrier souffle le verre",
        # Found as `l'anneau de recuisson` (x3). An anneau is a ring; the
        # course text itself describes "un four à programme de température".
        "l'arche de recuisson (f.)": "four à température programmée où la pièce terminée refroidit lentement",
        # Found as `cullet` (x4), the English word, left untranslated.
        "le calcin": "fragments de verre déjà fabriqué réintroduits dans le mélange",
        # Found as `glace incandescente` and `éclats de glace froide`. In
        # French glace is ice, or mirror glass — never the hot working
        # material. This entry exists to hold the ordinary word in place.
        "le verre": "le matériau travaillé, à chaud comme à froid",
        #
        # ── ATTESTED — human-authored French, course 101 (CERFAV) ──
        "la recuisson": "refroidissement lent et contrôlé qui supprime les tensions du verre",
        "le verrier": "l'artisan qui travaille le verre",
        "la verrerie": "l'atelier où le verre est travaillé, et sa production",
        "le soufflage": "mise en forme du verre par insufflation d'air",
        "l'insufflation (f.)": "action d'envoyer l'air dans la masse de verre",
        "l'étirage (m.)": "allongement du verre ramolli pour en réduire la section",
        "le ramollissement": "passage du verre à l'état plastique sous l'effet de la chaleur",
        "le coefficient de dilatation": "grandeur qui doit concorder entre deux verres assemblés",
        "le gabarit": "forme de référence servant à contrôler une pièce",
        "la viscosité": "résistance du verre à l'écoulement, qui varie avec la température",
        #
        # ── ATTESTED — machine output already verified correct in review ──
        "le pontil": "tige métallique qui tient la pièce par son fond une fois détachée de la canne",
        "le cueillage": "prélèvement de verre en fusion dans le four",
        "le biseau": "bord taillé en oblique",
        "le meulage": "usure à la meule pour dresser ou polir un bord",
        #
        # NOT listed, deliberately: `chalumeau`. It is genuine French and
        # course 101 uses it constantly — but 101 is lampworking, where a
        # chalumeau is a torch, and this glossary also covers furnace work.
        # Listing it made the model render "the tip of the blowpipe" as
        # "la mèche du chalumeau". Two sub-crafts share the name
        # "glassblowing"; their vocabulary is not interchangeable, and a term
        # that means different things in each does more harm than good.
    },
    # Category 34 in DOMAIN_MAP. No glovemaking course has been ingested, so
    # there is nothing in the corpus to mine and nothing to check a term
    # against. Left deliberately empty rather than filled by guesswork:
    # inventing vocabulary is the failure mode this whole module replaces.
    # Translation behaves exactly as it does today until terms are added.
    "glovemaking": {},
}


def glossary_prompt_fragment(craft: Optional[str]) -> str:
    """Return the glossary block for a craft, or "" when there is none.

    "" is the normal answer. Most of the corpus belongs to no craft, so every
    caller can concatenate this unconditionally and pay nothing.
    """
    terms = CRAFT_GLOSSARIES.get(craft or "")
    if not terms:
        return ""

    lines = "\n".join(f"- {term} : {gloss}" for term, gloss in terms.items())
    return (
        "Vocabulaire du métier. Lorsque le texte source désigne l'une de ces "
        "notions, emploie exactement ce terme, en respectant son genre "
        "grammatical (indiqué par l'article).\n"
        "N'emploie aucun de ces termes pour désigner autre chose, et n'en "
        "ajoute aucun que le texte source ne mentionne pas. Cette liste est "
        "une référence, pas un contenu à traduire ni à expliquer.\n"
        f"{lines}\n\n"
    )
