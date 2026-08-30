"""Retrieval-based response selection — replaces agent.py's random.choice
placeholder.

By the time a message reaches here, which objection has already been
decided by whoever built the Query: Query.encode() (stub.py) fans a
Query out into one wire line per choice type before it's ever queued
(see voiceChannel/internal/model/query.go's NewQuery, which builds one
Query per already-identified ObjectionState). So this module doesn't
detect objections — it selects the best of a set of already-scoped
candidate responses, given the prospect's actual words.

Under the epic's 100ms live budget (#1), there's no room for a separate
classification step before retrieval — embedding the utterance and
ranking it against candidates does selection and confidence scoring in
one pass, which is what RetrievalRecognizer.select does here.
"""

import math
from typing import Callable, List, Sequence, Tuple

Embedder = Callable[[str], Sequence[float]]

# Solve.choice when nothing clears the threshold. Silence is the correct
# output for a turn that isn't a confident match — not a forced guess
# (#7's open question on objections outside the taxonomy). Downstream
# (#8), an empty choice is what triggers handoff to the rep.
NO_CHOICE = ""


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class RetrievalRecognizer:
    """embed is injected rather than bound to a specific model or HTTP
    call, so this is testable without a running whisper_server.py or
    MLX hardware — #13 and #15 are what measure the real thing against
    real hardware. In production, embed should call whisper_server.py's
    /embed endpoint, the same one diary's lookup mode already uses
    (#16), so both sides rank in the same embedding space.
    """

    def __init__(
        self,
        embed: Embedder,
        threshold: float = 0.5,
        handoff_above: float = None,
        index=None,
    ):
        """`threshold` and `handoff_above` are the same line, named from the
        two ends it was named from in two repos.

        This one has always cut on *similarity*: play when `sim >= threshold`.
        The voice pipeline cuts on *uncertainty*: play when
        `uncertainty <= handoff_above`. Since `uncertainty = 1 - similarity`
        those are the same statement, and

            handoff_above = 1 - threshold

        exactly. Both spellings are accepted so neither side has to translate
        at the call site and get it backwards — passing `handoff_above=0.65`
        is passing `threshold=0.35`, and the class stores one of them.

        `index` is a `RetrievalIndex`. With one, `select` takes candidate
        **ids** and resolves them through it; without one it takes candidate
        **text** and embeds it per call, which is the original behaviour and
        is kept for callers that have no corpus to index.
        """
        if handoff_above is not None:
            threshold = 1.0 - handoff_above
        self.embed = embed
        self.threshold = threshold
        self.index = index

    @property
    def handoff_above(self) -> float:
        """The same line, expressed as the uncertainty it allows."""
        return 1.0 - self.threshold

    def select(self, utterance: str, candidates: List[str]) -> Tuple[str, float]:
        """Returns (choice, uncertainty).

        choice is NO_CHOICE when nothing clears self.threshold.

        uncertainty is 1 - best_similarity: low for a close match, high
        when nothing matched well. This is what Solve.uncertainty is
        meant to carry (#1's "play-or-handoff switch") — it still needs
        calibrating against real labelled data before it can be trusted
        as a probability rather than just a ranking (#7); this is the
        ranking half.

        Re-embeds every candidate on every call, same as diary's current
        lookup server does for its own corpus (#16) — fine for a
        library-sized candidate set, and not something to optimize
        without measuring first.
        """
        if not candidates:
            return NO_CHOICE, 1.0

        if self.index is not None:
            # Candidates are ids into the index, and their text is already
            # embedded there. One embedding for the turn rather than one per
            # candidate, which is what #1's 15 ms actually pays for.
            best_choice, best_sim = self.index.best(utterance, candidates)
            if not best_choice or best_sim < self.threshold:
                return NO_CHOICE, 1.0 - max(best_sim, 0.0)
            return best_choice, 1.0 - best_sim

        query_vec = self.embed(utterance)

        best_choice = NO_CHOICE
        best_sim = -1.0
        for candidate in candidates:
            sim = cosine_similarity(query_vec, self.embed(candidate))
            if sim > best_sim:
                best_sim = sim
                best_choice = candidate

        if best_sim < self.threshold:
            return NO_CHOICE, 1.0 - max(best_sim, 0.0)

        return best_choice, 1.0 - best_sim
