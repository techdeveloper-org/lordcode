"""BM25 term weighting over graph-enriched profile text.

Two decisions here do the real work, and neither is about the scoring formula.

FIRST, an agent's document is built by TRAVERSING, not by reading its own
record. An agent record's description is about 110 characters -- far too little
to match a task against. Following AGENT_USES_SKILL and pulling in each
skill's name and description gives roughly 1800 characters of genuinely
relevant vocabulary. This is what lets "add an endpoint that creates an order"
reach a backend agent: the word "endpoint" is not in the agent's description,
it is in api-design-core's, one edge away. A ranker over agent descriptions
alone cannot see it, which is why the existing implementation answers
figma-automation-engineer for that task.

SECOND, descriptions missing from the registries are backfilled from markdown.
147 agents and 134 skills have no registry description at all, and all 281
have one in their frontmatter. Without the backfill those entries are ranked
on their name alone.

BM25 rather than plain IDF because document lengths here differ by more than
an order of magnitude -- an agent enriched with 22 mandatory skills against one
with a single skill -- and unnormalised term frequency would simply prefer the
longest document.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Mapping

K1 = 1.2
"""Term-frequency saturation. The standard Okapi value: a term occurring ten
times signals little more than five, which matters here because a domain's
aggregate text repeats its own vocabulary heavily."""

B = 0.75
"""Length normalisation strength. The standard Okapi value, and load-bearing
given the document-length spread described in the module docstring."""

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[+#.][a-z0-9]+)*[+#]*")

STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those with without within
    for from to into onto of on in at by as is are was were be been being do
    does did doing have has had having it its they them their there here when
    where which who whom whose what why how all any both each few more most
    other some such no nor not only own same so too very can will just should
    now use used using uses via per also i you we he she our your my me
    add adds added make makes made get gets got set sets write writes writing
    build builds building create creates creating implement implements
    need needs needed want wants like new one two three
    """.split()
)
"""Terms carrying no discriminative signal for this corpus.

Includes the generic engineering verbs -- add, build, create, implement,
write -- deliberately. Nearly every task in this domain opens with one, so
they appear in most documents and in most queries, contributing noise with a
near-zero IDF while inflating length normalisation.
"""


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords and 1-char tokens.

    Keeps `+`, `#` and `.` inside a token, and a trailing run of `+`/`#`, so
    c++, c#, node.js and asp.net survive as single terms. Without the trailing
    case, "c++" tokenized to a bare "c" which the length filter then dropped --
    the language name disappeared from the corpus entirely.
    """
    return [
        token
        for token in TOKEN_PATTERN.findall(text.lower())
        if len(token) > 1 and token not in STOPWORDS
    ]


@dataclass
class Document:
    """One scoreable unit: an id, its token counts, and its length."""

    id: str
    counts: Mapping[str, int]
    length: int
    kind: str = ""

    @classmethod
    def from_text(cls, doc_id: str, text: str, kind: str = "") -> "Document":
        """Tokenize text into a scoreable document."""
        tokens = tokenize(text)
        return cls(id=doc_id, counts=Counter(tokens), length=len(tokens), kind=kind)


@dataclass
class Lexicon:
    """A BM25 index over a fixed document set."""

    documents: dict[str, Document] = field(default_factory=dict)
    _document_frequency: dict[str, int] = field(default_factory=dict, repr=False)
    _average_length: float = 0.0

    @classmethod
    def build(cls, documents: Iterable[Document]) -> "Lexicon":
        """Index documents, computing document frequencies and mean length."""
        by_id = {document.id: document for document in documents}
        frequency: Counter[str] = Counter()
        for document in by_id.values():
            frequency.update(document.counts.keys())

        total_length = sum(document.length for document in by_id.values())
        average = (total_length / len(by_id)) if by_id else 0.0
        return cls(documents=by_id, _document_frequency=dict(frequency), _average_length=average)

    @property
    def size(self) -> int:
        """Number of indexed documents."""
        return len(self.documents)

    @property
    def vocabulary_size(self) -> int:
        """Number of distinct terms across the corpus."""
        return len(self._document_frequency)

    def idf(self, term: str) -> float:
        """Inverse document frequency, floored at zero.

        Uses the standard BM25 form with the +0.5 smoothing. A term present in
        more than half the corpus gets a negative raw value there, which would
        make a common word actively count AGAINST a document; flooring at zero
        makes such a term merely uninformative instead.
        """
        occurrences = self._document_frequency.get(term, 0)
        if occurrences == 0:
            return 0.0
        raw = math.log((self.size - occurrences + 0.5) / (occurrences + 0.5) + 1.0)
        return max(0.0, raw)

    def score(self, query_terms: Iterable[str], document_id: str) -> float:
        """BM25 score of one document against pre-tokenized query terms."""
        document = self.documents.get(document_id)
        if document is None or document.length == 0:
            return 0.0

        total = 0.0
        normaliser = K1 * (1 - B + B * (document.length / self._average_length)) if self._average_length else K1
        for term in query_terms:
            frequency = document.counts.get(term, 0)
            if not frequency:
                continue
            total += self.idf(term) * (frequency * (K1 + 1)) / (frequency + normaliser)
        return total

    def coverage(self, query_terms: Iterable[str], document_id: str) -> float:
        """Share of the query's total IDF weight that this document contains.

        BM25 sums per-term contributions, so a document repeating ONE common
        query term can outscore a document containing four rarer ones. That is
        not a hypothetical: "add an endpoint that creates an order and returns
        its identifier" ranked a demand-planning agent first, because
        supply-chain text says "order" constantly, while the backend agent
        matching endpoint AND order AND identifier scored lower.

        Coverage is measured in IDF weight rather than in term count so that
        matching one rare term still counts for more than matching two common
        ones -- a plain count would treat every term as equally telling.

        Returns:
            0.0 when the query carries no weight, else the covered fraction.
        """
        document = self.documents.get(document_id)
        if document is None:
            return 0.0

        total = 0.0
        covered = 0.0
        for term in set(query_terms):
            weight = self.idf(term)
            total += weight
            if term in document.counts:
                covered += weight
        return (covered / total) if total > 0 else 0.0

    def rank(self, query_terms: Iterable[str], candidates: Iterable[str] | None = None) -> list[tuple[str, float]]:
        """Score candidates against the query, best first.

        Args:
            query_terms: Pre-tokenized query.
            candidates: Document ids to consider. Defaults to every document.

        Returns:
            (document_id, score) pairs sorted by descending score then id, so
            ties break deterministically rather than by dict order -- replay
            (see the manifest) depends on this being stable.
        """
        terms = list(query_terms)
        pool = list(candidates) if candidates is not None else list(self.documents)
        scored = [(doc_id, self.score(terms, doc_id)) for doc_id in pool]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored
