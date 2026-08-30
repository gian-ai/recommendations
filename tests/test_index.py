"""The retrieval index — what the recognizer scores against.

The behaviour worth pinning is not "it returns the closest thing". It is the
three decisions that make the index worth having at all: one embedding per
turn rather than one per candidate, the *objection* as the indexed text rather
than the answer, and a best-of across an entry's phrasings so a paraphrase
only has to land near one of them.
"""

import pytest

from src.actors.index import Entry, RetrievalIndex
from src.actors.recognizer import NO_CHOICE, RetrievalRecognizer


def counting_embedder(vocab):
    """Bag-of-words over a fixed vocabulary, and a call counter.

    Literal token overlap only — nothing a deployment should use, and exactly
    what pins a claim about *how many times* embed was called.
    """
    calls = []

    def embed(text):
        calls.append(text)
        words = text.lower().replace(",", "").replace("?", "").replace(".", "").split()
        return [float(words.count(w)) for w in vocab]

    embed.calls = calls
    return embed


VOCAB = sorted({
    "expensive", "price", "budget", "cost", "over", "pricing", "volume",
    "secure", "security", "data", "safe", "soc", "certified", "audit",
    "timeline", "pilot", "schedule", "start", "your", "product", "is", "too",
    "way", "what", "about", "our", "how", "do", "we", "know", "with", "you",
})


# ── one embedding per turn ───────────────────────────────────────────────


def test_a_turn_costs_one_embedding_not_one_per_candidate():
    """The reason this class exists. #1 allots embedding 15 ms of the live
    budget — one round trip. Re-embedding every candidate made a library of
    forty answers cost forty-one, and the budget was gone before ranking."""
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    for n in range(5):
        index.add(f"clip_{n}", ["your product is too expensive"], [[1.0] * len(VOCAB)])

    embed.calls.clear()
    index.best("your product is too expensive")

    assert len(embed.calls) == 1, f"embedded {len(embed.calls)} times for one turn"


def test_supplied_vectors_are_not_recomputed():
    """The caller has usually embedded these already and written them down;
    recomputing is work the system has done and thrown away."""
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_1", ["your product is too expensive"], [[1.0] * len(VOCAB)])

    index.best("what about price")
    index.best("what about price")

    assert index.embedded == 0, "an indexed vector was embedded anyway"


def test_a_missing_vector_is_filled_in_once():
    """Supplying vectors is an optimisation, not a requirement."""
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_1", ["your product is too expensive"])

    index.best("what about price")
    index.best("what about price")

    assert index.embedded == 1, "the entry was embedded more than once"


def test_a_vector_never_outlives_its_phrasing():
    """More vectors than phrasings would pair text with someone else's
    embedding, which reads as a ranking bug a long way from here."""
    index = RetrievalIndex(counting_embedder(VOCAB))

    entry = index.add("clip_1", ["only one"], [[1.0], [2.0], [3.0]])

    assert len(entry.vectors) == 1


# ── the objection is what gets indexed ───────────────────────────────────


def test_an_objection_finds_the_answer_indexed_for_it():
    """Indexing the *answer* instead scores the right entry near zero: a good
    answer does not repeat the question back."""
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", ["your product is too expensive"])
    index.add("clip_security", ["how do we know our data is safe with you"])

    choice, similarity = index.best("your product is too expensive")

    assert choice == "clip_price"
    assert similarity == pytest.approx(1.0)


def test_an_unrelated_utterance_does_not_win_by_default():
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", ["your product is too expensive"])

    _, similarity = index.best("pilot schedule timeline")

    assert similarity == pytest.approx(0.0)


# ── best-of across phrasings ─────────────────────────────────────────────


def test_any_phrasing_finds_the_entry():
    """Measured on held-out paraphrases, one phrasing per entry matched 3 of
    10 and three matched 9 of 10."""
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", [
        "your product is too expensive",
        "that is way over budget",
    ])
    index.add("clip_security", ["how do we know our data is safe with you"])

    choice, similarity = index.best("way over budget")

    assert choice == "clip_price"
    assert similarity > 0.0


def test_a_new_phrasing_does_not_dilute_the_old_ones():
    """Scoring takes a maximum, so a phrasing is another way in, never a
    weakening of the ones already there."""
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", ["your product is too expensive"])
    before = index.best("your product is too expensive")[1]

    index.learn("clip_price", "pilot schedule timeline")

    assert index.best("your product is too expensive")[1] == pytest.approx(before)


def test_a_phrasing_is_learned_once():
    index = RetrievalIndex(counting_embedder(VOCAB))
    index.add("clip_price", ["your product is too expensive"])

    assert index.learn("clip_price", "way over budget") is True
    assert index.learn("clip_price", "way over budget") is False
    assert index.learn("clip_price", "  Way Over Budget  ") is False
    assert index.learn("clip_price", "your product is too expensive") is False


def test_learning_against_an_unknown_entry_is_not_fatal():
    """This runs while a call is live. A phrasing that cannot be filed costs a
    little future accuracy, not the conversation."""
    index = RetrievalIndex(counting_embedder(VOCAB))

    assert index.learn("no_such_clip", "anything") is False


def test_a_learned_phrasing_keeps_its_own_vector():
    index = RetrievalIndex(counting_embedder(VOCAB))
    index.add("clip_price", ["your product is too expensive"], [[1.0] * len(VOCAB)])

    index.learn("clip_price", "way over budget", [2.0] * len(VOCAB))
    entry = index.get("clip_price")

    assert entry.vectors == [[1.0] * len(VOCAB), [2.0] * len(VOCAB)]


# ── scoping ──────────────────────────────────────────────────────────────


def test_candidates_scope_the_search():
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", ["your product is too expensive"])
    index.add("clip_security", ["how do we know our data is safe with you"])

    choice, _ = index.best("your product is too expensive", ["clip_security"])

    assert choice == "clip_security", "a candidate outside the scope was returned"


def test_an_unknown_candidate_id_is_skipped_not_raised():
    """A caller's view of the library and this index can legitimately differ
    by one turn."""
    index = RetrievalIndex(counting_embedder(VOCAB))
    index.add("clip_price", ["your product is too expensive"])

    choice, _ = index.best("expensive", ["clip_price", "clip_gone"])

    assert choice == "clip_price"


def test_scored_is_ordered_best_first():
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", ["your product is too expensive"])
    index.add("clip_security", ["how do we know our data is safe with you"])

    scores = index.scored("your product is too expensive")

    assert [i for i, _ in scores] == ["clip_price", "clip_security"]
    assert scores[0][1] >= scores[1][1]


def test_an_empty_index_returns_nothing_rather_than_raising():
    index = RetrievalIndex(counting_embedder(VOCAB))

    assert index.best("anything") == ("", 0.0)
    assert index.scored("anything") == []


# ── the recognizer, driving the index ────────────────────────────────────


def test_the_recognizer_resolves_ids_through_the_index():
    """The defect this closes: without an index the recognizer embedded the
    literal string "clip_001" and compared it to what the caller said."""
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", ["your product is too expensive"])
    index.add("clip_security", ["how do we know our data is safe with you"])
    recognizer = RetrievalRecognizer(embed=embed, handoff_above=0.9, index=index)

    choice, uncertainty = recognizer.select(
        "your product is too expensive", ["clip_price", "clip_security"]
    )

    assert choice == "clip_price"
    assert uncertainty == pytest.approx(0.0)


def test_the_recognizer_hands_off_when_nothing_is_close_enough():
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", ["your product is too expensive"])
    recognizer = RetrievalRecognizer(embed=embed, handoff_above=0.1, index=index)

    choice, uncertainty = recognizer.select("pilot schedule timeline", ["clip_price"])

    assert choice == NO_CHOICE
    assert uncertainty == pytest.approx(1.0)


def test_the_two_threshold_spellings_are_the_same_line():
    """`handoff_above` cuts on uncertainty and `threshold` cuts on similarity.
    Since uncertainty is 1 - similarity they are the same statement, and the
    class stores one of them — passing the wrong one backwards is the bug this
    prevents."""
    embed = counting_embedder(VOCAB)

    assert RetrievalRecognizer(embed=embed, threshold=0.35).handoff_above == pytest.approx(0.65)
    assert RetrievalRecognizer(embed=embed, handoff_above=0.65).threshold == pytest.approx(0.35)


def test_without_an_index_candidates_are_still_text():
    """The original behaviour, kept for callers with no corpus to index."""
    embed = counting_embedder(VOCAB)
    recognizer = RetrievalRecognizer(embed=embed, threshold=0.05)

    choice, _ = recognizer.select(
        "what about price",
        ["we have volume pricing that helps with price", "pilot schedule timeline"],
    )

    assert choice == "we have volume pricing that helps with price"


# ── the same question, twice in one turn ─────────────────────────────────


def test_a_turn_that_asks_twice_embeds_once():
    """A turn asks the same question twice: the decision path calls best(),
    then the panel calls scored() for the shortlist, on the same words. That
    was two round trips out of a budget that allots one, for a vector that
    cannot have changed."""
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", ["your product is too expensive"], [[1.0] * len(VOCAB)])

    embed.calls.clear()
    index.best("way over budget")
    index.scored("way over budget")

    assert len(embed.calls) == 1, f"embedded {len(embed.calls)} times for one turn"
    assert index.query_hits == 1


def test_a_different_utterance_is_embedded_again():
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", ["your product is too expensive"], [[1.0] * len(VOCAB)])

    embed.calls.clear()
    index.best("way over budget")
    index.best("what about security")

    assert len(embed.calls) == 2
    assert index.query_hits == 0


def test_the_cached_query_gives_the_same_answer():
    """A cache that changed a decision would be worse than the round trip."""
    embed = counting_embedder(VOCAB)
    index = RetrievalIndex(embed)
    index.add("clip_price", ["your product is too expensive"])
    index.add("clip_security", ["how do we know our data is safe with you"])

    first = index.scored("your product is too expensive")
    second = index.scored("your product is too expensive")

    assert first == second
