"""The retrieval index — candidates kept embedded, so a turn costs one
embedding rather than one per candidate.

RetrievalRecognizer scores; this is what it scores against. Splitting them is
the point: select() re-embedded every candidate on every call, which is fine
for a handful of strings in a test and wrong for a real corpus. Under the
epic's 100ms live budget (#1), embedding gets 15ms — one round trip, not one
per candidate. A library of forty banked answers made forty-one.

An entry is not a string. It is an answer, and every way the objection it
answers has been put:

    Entry(id='clip_004',
          phrasings=['Your product is too expensive.',
                     'that is way over what we budgeted'])

Both halves of that shape are load-bearing.

The text indexed is the objection, not the answer. A good answer does not
repeat the question — "We're priced above the others because we replaced three
tools" shares nothing with "Your product is too expensive." Indexing answers
and matching objections against them scores the right entry near zero and
hands off something already banked. Measured through a sentence embedder on
one such pair: 0.249 against the answer, 1.000 against the objection.

One phrasing is not enough, because a prospect does not say the sentence the
rep recorded. Scoring takes the best match across an entry's phrasings, so
each is another way in rather than a dilution. Measured on held-out
paraphrases the index had never seen, one phrasing per entry matched 3 of 10
and three matched 9 of 10, with no entry answering for another.

Phrasings are earned. An Observe pairing an utterance with a choice a human
made is a labelled paraphrase from the distribution that matters, and learn()
is how it gets in. Choices the system made itself are deliberately not fed
back — an index trained on its own guesses widens its own mistakes.

embed is injected and vectors are plain floats, so this stays importable with
nothing installed: the queue is stdlib asyncio and this repo does not get a
numpy floor for a dot product over 384 numbers.
"""

from typing import Callable, Iterable, Sequence

from src.actors.recognizer import cosine_similarity
from src.communicate.stub import BaseModel

Embedder = Callable[[str], Sequence[float]]


class Entry(BaseModel):
    """One candidate, and every way the objection it answers has been put.

    vectors is positional to phrasings and allowed to be shorter: a caller
    with vectors already on disk passes them, and anything missing is embedded
    on first use rather than demanded up front.
    """
    id:str
    phrasings:list[str]=[]
    vectors:list[list[float]]=[]

    def knows(self, phrasing:str) -> bool:
        folded = phrasing.strip().casefold()
        return any(p.strip().casefold() == folded for p in self.phrasings)


class RetrievalIndex:
    """Candidates, kept embedded.

    Deliberately not persistent. Whoever owns the corpus owns where it lives —
    in the voice pipeline that is diary's datalake, which this repo has no
    business knowing about. This holds the embedded form and answers questions
    about it; loading and saving belong to the caller.
    """

    def __init__(self, embed:Embedder):
        self.embed = embed
        self.entries:dict[str,Entry] = dict()
        # The last utterance embedded, and its vector. One entry, because a
        # turn asks the same question twice and never a third time: the
        # decision path calls best() and the panel then calls scored() for the
        # shortlist, on the same words. That was two round trips out of a
        # budget that allots one, for a vector that cannot have changed —
        # embedding is a pure function of the text.
        #
        # Not an LRU. Turns are sequential and a second utterance means the
        # first will not be asked again, so anything larger would be holding
        # vectors nobody comes back for.
        self.last_query:tuple = ('', None)
        self.query_hits = 0
        # How many vectors had to be computed because none was supplied. A
        # caller that thinks it is passing vectors in and sees this climbing
        # is losing the budget it thought it had saved.
        self.embedded = 0

    def __len__(self) -> int:
        return len(self.entries)

    def __contains__(self, entry_id:str) -> bool:
        return entry_id in self.entries

    def ids(self) -> list:
        return list(self.entries)

    def get(self, entry_id:str) -> Entry:
        return self.entries.get(entry_id)

    def add(self, entry_id:str, phrasings:Iterable[str], vectors:Iterable=None) -> Entry:
        """Index one candidate, replacing any entry already under that id.

        Supplying vectors is what keeps a restart cheap — the caller has
        usually embedded these already and written them down — and omitting
        them costs one embedding per phrasing, once, at first use.
        """
        kept = [p.strip() for p in phrasings if p and p.strip()]
        supplied = [list(v) for v in (vectors or list())]
        # Never let a vector outlive the phrasing it belongs to: a longer list
        # would silently pair text with someone else's embedding.
        del supplied[len(kept):]
        entry = Entry(id=entry_id, phrasings=kept, vectors=supplied)
        self.entries[entry_id] = entry
        return entry

    def learn(self, entry_id:str, phrasing:str, vector:Sequence[float]=None) -> bool:
        """Remember another way this objection was put. True if it was new.

        Deduplicated on the text as spoken: scoring takes a maximum across
        phrasings, so a repeat changes no decision and only costs an embedding.
        """
        entry = self.entries.get(entry_id)
        phrasing = (phrasing or '').strip()
        if entry is None or not phrasing or entry.knows(phrasing):
            return False

        while len(entry.vectors) < len(entry.phrasings):
            entry.vectors.append(list())
        entry.phrasings.append(phrasing)
        entry.vectors.append(list(vector) if vector else list())
        return True

    def vectors_for(self, entry:Entry) -> list:
        """Every phrasing's vector, filling in any the caller did not supply."""
        while len(entry.vectors) < len(entry.phrasings):
            entry.vectors.append(list())
        for position, phrasing in enumerate(entry.phrasings):
            if not entry.vectors[position]:
                entry.vectors[position] = list(self.embed(phrasing))
                self.embedded += 1
        return [v for v in entry.vectors if v]

    def embed_query(self, utterance:str) -> Sequence[float]:
        """The utterance's vector, reusing the one from the turn before it."""
        text, vector = self.last_query
        if vector is not None and text == utterance:
            self.query_hits += 1
            return vector
        vector = self.embed(utterance)
        self.last_query = (utterance, vector)
        return vector

    def scored(self, utterance:str, candidates:Iterable[str]=None) -> list:
        """(id, similarity) per candidate, best first.

        One embedding of the utterance however many candidates there are,
        which is the whole reason this class exists. An entry scores as its
        best phrasing, so a prospect only has to land near one of the ways the
        objection has been heard.

        candidates scopes the search to a subset of ids. An unknown id is
        skipped rather than raising: a caller's view of the library and this
        index can legitimately differ by one turn.
        """
        wanted = list(candidates) if candidates is not None else self.ids()
        entries = [e for e in (self.entries.get(i) for i in wanted) if e is not None]
        if not entries:
            return list()

        query = self.embed_query(utterance)
        scores = [
            (entry.id, max((cosine_similarity(query, v) for v in self.vectors_for(entry)),
                           default=0.0))
            for entry in entries
        ]
        return sorted(scores, key=lambda pair: pair[1], reverse=True)

    def best(self, utterance:str, candidates:Iterable[str]=None) -> tuple:
        """The closest candidate and its similarity, or ('', 0.0) for nothing."""
        scores = self.scored(utterance, candidates)
        return scores[0] if scores else ('', 0.0)
