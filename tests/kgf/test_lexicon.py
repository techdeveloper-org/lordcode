"""Tests for tokenization and BM25 scoring."""

from __future__ import annotations

from kgf.lexicon import B, K1, Document, Lexicon, tokenize


def _lexicon(**texts: str) -> Lexicon:
    return Lexicon.build(Document.from_text(doc_id, text) for doc_id, text in texts.items())


def test_tokenize_lowercases_and_splits():
    assert tokenize("Spring Boot REST Endpoint") == ["spring", "boot", "rest", "endpoint"]


def test_tokenize_keeps_language_names_intact():
    """c++ and node.js must survive as single terms, not fragment into noise."""
    tokens = tokenize("write c++ and node.js and c# and asp.net code")
    assert "c++" in tokens
    assert "node.js" in tokens
    assert "c#" in tokens
    assert "asp.net" in tokens


def test_tokenize_drops_stopwords_and_single_characters():
    assert tokenize("the a of x and") == []


def test_tokenize_drops_generic_engineering_verbs():
    """Nearly every task opens with one, so they carry no signal here."""
    for verb in ("add", "build", "create", "implement", "write", "make"):
        assert verb not in tokenize(f"{verb} a service")


def test_idf_is_higher_for_rarer_terms():
    lexicon = _lexicon(a="common rare", b="common", c="common", d="common")
    assert lexicon.idf("rare") > lexicon.idf("common")


def test_idf_of_an_unseen_term_is_zero():
    assert _lexicon(a="hello").idf("absent") == 0.0


def test_idf_never_goes_negative():
    """A term in most documents must become uninformative, not count against.

    The raw BM25 form goes negative past half the corpus, which would make a
    common word actively penalise the documents containing it.
    """
    lexicon = _lexicon(a="ubiquitous", b="ubiquitous", c="ubiquitous", d="unique")
    assert lexicon.idf("ubiquitous") >= 0.0


def test_score_is_zero_when_no_term_matches():
    lexicon = _lexicon(a="alpha beta")
    assert lexicon.score(["gamma"], "a") == 0.0


def test_score_is_zero_for_an_unknown_document():
    assert _lexicon(a="alpha").score(["alpha"], "missing") == 0.0


def test_length_normalisation_prefers_the_focused_document():
    """The reason for BM25 rather than plain IDF.

    Document lengths here differ by more than an order of magnitude -- an agent
    enriched with 22 skills against one with a single skill -- so unnormalised
    term frequency would simply prefer whichever document is longest.
    """
    padding = " ".join(f"filler{index}" for index in range(400))
    lexicon = _lexicon(focused="payments refund", padded=f"payments refund {padding}")
    assert lexicon.score(["payments"], "focused") > lexicon.score(["payments"], "padded")


def test_term_frequency_saturates():
    """Ten occurrences must not be worth ten times one."""
    lexicon = _lexicon(once="alpha beta gamma", many="alpha " * 10 + "beta gamma")
    once = lexicon.score(["alpha"], "once")
    many = lexicon.score(["alpha"], "many")
    assert many > once
    assert many < once * 10


def test_coverage_weighs_by_idf_not_by_term_count():
    """Matching one rare term beats matching two common ones.

    A plain count would call those equal, which is what lets a document
    repeating a common query term outrank a genuinely relevant one.
    """
    lexicon = _lexicon(
        rare_only="esoteric",
        common_only="ubiquitous alternative",
        both="esoteric ubiquitous alternative",
        filler1="ubiquitous alternative",
        filler2="ubiquitous alternative",
    )
    query = ["esoteric", "ubiquitous", "alternative"]
    assert lexicon.coverage(query, "both") == 1.0
    assert lexicon.coverage(query, "rare_only") > lexicon.coverage(query, "common_only")


def test_coverage_is_zero_for_an_unknown_document():
    assert _lexicon(a="alpha").coverage(["alpha"], "missing") == 0.0


def test_rank_orders_by_score_then_id_deterministically():
    """Replay depends on a stable order, so ties must not follow dict order."""
    lexicon = _lexicon(zebra="alpha", alpha="alpha", middle="alpha")
    first = lexicon.rank(["alpha"])
    second = lexicon.rank(["alpha"])
    assert first == second
    scores = [score for _doc_id, score in first]
    assert scores == sorted(scores, reverse=True)


def test_rank_restricted_to_candidates():
    lexicon = _lexicon(a="alpha", b="alpha")
    ranked = lexicon.rank(["alpha"], candidates=["b"])
    assert [doc_id for doc_id, _score in ranked] == ["b"]


def test_standard_okapi_constants_are_used():
    """Pinned so a future change is a deliberate decision, not a drift."""
    assert K1 == 1.2
    assert B == 0.75


def test_empty_corpus_does_not_divide_by_zero():
    lexicon = Lexicon.build([])
    assert lexicon.size == 0
    assert lexicon.score(["anything"], "nothing") == 0.0
