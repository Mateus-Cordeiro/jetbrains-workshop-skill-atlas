"""Rank catalog metadata locally; no document retrieval or persistent index."""

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

from skill_atlas.errors import AtlasError
from skill_atlas.models import Repository, Skill
from skill_atlas.ports import CatalogReader

_STOPWORDS = frozenset(
    "a an and are as at be by for from in is it of on or that the this to "
    "use using when with you your skill skills".split()
)
_TOKEN = re.compile(r"[^\W_]+(?:\+\+|#)?", re.UNICODE)
_MIN_SCORE = 10.0
_LIMIT = 10


class MissingSimilaritySource(AtlasError):
    pass


@dataclass(frozen=True)
class SimilarMatch:
    locations: tuple[Skill, ...]
    score: float
    shared_terms: tuple[str, ...]

    @property
    def skill(self) -> Skill:
        return self.locations[0]

    @property
    def display_score(self) -> int:
        return math.floor(self.score + 0.5)


@dataclass(frozen=True)
class SimilarityResult:
    source: Skill
    matches: tuple[SimilarMatch, ...]


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _metadata(skill: Skill) -> tuple[str, str]:
    return _normalized(skill.name), _normalized(skill.description)


def _terms(text: str) -> Counter[str]:
    text = unicodedata.normalize("NFKC", text)
    text = text.casefold()
    tokens = _TOKEN.findall(text)
    terms = Counter(token for token in tokens if token not in _STOPWORDS)
    terms.update(
        f"{left} {right}"
        for left, right in zip(tokens, tokens[1:], strict=False)
        if left not in _STOPWORDS and right not in _STOPWORDS
    )
    return terms


def _vectors(texts: list[str]) -> list[dict[str, float]]:
    documents = [_terms(text) for text in texts]
    frequencies = Counter(term for document in documents for term in document)
    vectors = []
    for document in documents:
        vector = {
            term: (1 + math.log(count))
            * (1 + math.log((len(documents) + 1) / (frequencies[term] + 1)))
            for term, count in document.items()
        }
        norm = math.sqrt(sum(weight * weight for weight in vector.values()))
        vectors.append({term: weight / norm for term, weight in vector.items()} if norm else {})
    return vectors


def _order(skill: Skill) -> tuple[str, str, str]:
    return skill.name.casefold(), skill.repository.url, skill.path


class SimilarSkills:
    def __init__(self, catalog: CatalogReader) -> None:
        self.catalog = catalog

    def search(
        self, repository: Repository, path: str, *, other_repositories: bool = False
    ) -> SimilarityResult:
        # Resolve the source from the same read transaction as every candidate.
        skills = self.catalog.all_skills()
        source = next(
            (s for s in skills if s.repository.url == repository.url and s.path == path), None
        )
        if source is None:
            raise MissingSimilaritySource(
                "The starting skill is no longer in the catalog. Choose another skill."
            )
        groups: dict[tuple[str, str], list[Skill]] = defaultdict(list)
        for skill in skills:
            groups[_metadata(skill)].append(skill)
        keys = sorted(groups)
        names = _vectors([name for name, _ in keys])
        descriptions = _vectors([description for _, description in keys])
        source_index = keys.index(_metadata(source))
        matches = []
        for index, key in enumerate(keys):
            locations = tuple(
                sorted(
                    (
                        skill
                        for skill in groups[key]
                        if (skill.repository.url, skill.path) != (repository.url, path)
                        and (not other_repositories or skill.repository.url != repository.url)
                    ),
                    key=_order,
                )
            )
            if not locations:
                continue
            contributions: dict[str, float] = defaultdict(float)
            for vectors, weight in ((names, 0.2), (descriptions, 0.8)):
                for term, value in vectors[source_index].items():
                    if term in vectors[index]:
                        contributions[term] += weight * value * vectors[index][term]
            score = min(100.0, max(0.0, 100 * sum(contributions.values())))
            if score < _MIN_SCORE:
                continue
            shared = tuple(sorted(contributions, key=lambda term: (-contributions[term], term))[:3])
            matches.append(SimilarMatch(locations, score, shared))
        matches.sort(key=lambda match: (-match.score, _order(match.skill)))
        return SimilarityResult(source, tuple(matches[:_LIMIT]))
