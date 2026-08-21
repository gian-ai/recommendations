import pytest

from src.actors.recognizer import NO_CHOICE, RetrievalRecognizer, cosine_similarity


def _bag_of_words_embedder(vocab):
    """Deterministic toy embedder: bag-of-words counts over a fixed
    vocabulary. Not semantically meaningful beyond literal token overlap
    — exactly what a test needs, and nothing a real deployment should
    use. Production wires RetrievalRecognizer to whisper_server.py's
    /embed instead.
    """

    def embed(text):
        words = text.lower().replace(",", "").replace(".", "").split()
        return [float(words.count(w)) for w in vocab]

    return embed


# ── cosine_similarity ────────────────────────────────────────────────────


def test_cosine_similarity_identical_vectors():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector_is_zero_not_nan():
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cosine_similarity_mismatched_lengths_is_zero():
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


# ── RetrievalRecognizer.select ───────────────────────────────────────────


def test_select_returns_the_closer_candidate():
    utterance = "that sounds too expensive what about price"
    candidate_price = "we do have volume pricing that helps with price"
    candidate_timing = "we could start with a short pilot and flexible schedule"

    vocab = sorted(set((utterance + " " + candidate_price + " " + candidate_timing).split()))
    recognizer = RetrievalRecognizer(embed=_bag_of_words_embedder(vocab), threshold=0.05)

    choice, uncertainty = recognizer.select(utterance, [candidate_price, candidate_timing])

    assert choice == candidate_price
    assert 0.0 <= uncertainty <= 1.0


def test_select_returns_no_choice_below_threshold():
    # A strict threshold with a candidate that shares no vocabulary at
    # all — the point being that NO_CHOICE, not a confident wrong
    # answer, is the correct output here.
    utterance = "completely unrelated topic entirely"
    candidate = "we offer volume pricing past ten seats"

    vocab = sorted(set((utterance + " " + candidate).split()))
    recognizer = RetrievalRecognizer(embed=_bag_of_words_embedder(vocab), threshold=0.9)

    choice, uncertainty = recognizer.select(utterance, [candidate])

    assert choice == NO_CHOICE
    assert uncertainty > 0.5


def test_select_with_no_candidates_returns_no_choice():
    recognizer = RetrievalRecognizer(embed=lambda t: [1.0], threshold=0.1)
    choice, uncertainty = recognizer.select("anything", [])
    assert choice == NO_CHOICE
    assert uncertainty == 1.0


def test_select_never_calls_embed_when_there_are_no_candidates():
    # Regression guard: embedding is the expensive part (a real
    # deployment calls out to whisper_server.py's /embed) — don't pay
    # for it when there's nothing to rank against.
    calls = []

    def counting_embed(text):
        calls.append(text)
        return [1.0]

    recognizer = RetrievalRecognizer(embed=counting_embed, threshold=0.1)
    recognizer.select("anything", [])
    assert calls == []
