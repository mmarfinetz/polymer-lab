"""Seed-library sampling and chemically validated genetic mutation."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from .models import PolymerCandidate
from .protocols import CandidateValidator
from .validation import unique_candidates


@dataclass(frozen=True)
class StringMutation:
    name: str
    pattern: str
    replacement: str


DEFAULT_MUTATIONS = (
    StringMutation("phenyl_to_pyridyl", "c1ccccc1", "c1ccncc1"),
    StringMutation("pyridyl_to_phenyl", "c1ccncc1", "c1ccccc1"),
    StringMutation("ether_to_methylene", "COC", "CCC"),
    StringMutation("methylene_to_ether", "CCC", "COC"),
    StringMutation("methyl_to_fluoro", "(C)", "(F)"),
    StringMutation("fluoro_to_methyl", "(F)", "(C)"),
    StringMutation("carbonyl_to_sulfone", "C(=O)", "S(=O)(=O)"),
    StringMutation("sulfone_to_carbonyl", "S(=O)(=O)", "C(=O)"),
    StringMutation("phenylene_rigidification", "CC", "Cc1ccc(cc1)C"),
)


class GeneticMutationGenerator:
    """Applies auditable transformations and accepts only validator-approved offspring."""

    def __init__(
        self,
        validator: CandidateValidator,
        *,
        mutations: Sequence[StringMutation] = DEFAULT_MUTATIONS,
        random_seed: int = 42,
        max_attempt_multiplier: int = 30,
    ) -> None:
        self.validator = validator
        self.mutations = tuple(mutations)
        self.random = random.Random(random_seed)
        self.max_attempt_multiplier = max_attempt_multiplier

    def generate(
        self,
        parents: Sequence[PolymerCandidate],
        count: int,
        generation: int,
        *,
        preferred_mutations: Sequence[str] = (),
    ) -> list[PolymerCandidate]:
        if not parents or count <= 0:
            return []
        available = {mutation.name: mutation for mutation in self.mutations}
        unknown = set(preferred_mutations) - set(available)
        if unknown:
            raise ValueError(f"unknown mutation strategies: {sorted(unknown)}")
        mutation_pool = (
            tuple(available[name] for name in preferred_mutations) if preferred_mutations else self.mutations
        )
        offspring: list[PolymerCandidate] = []
        existing = {parent.structure_hash for parent in parents}
        attempts = 0
        while len(offspring) < count and attempts < count * self.max_attempt_multiplier:
            attempts += 1
            parent = self.random.choice(parents)
            applicable = [m for m in mutation_pool if m.pattern in parent.canonical_psmiles]
            if not applicable:
                continue
            mutation = self.random.choice(applicable)
            mutated = parent.canonical_psmiles.replace(mutation.pattern, mutation.replacement, 1)
            try:
                candidate = self.validator.validate(
                    mutated,
                    parent_ids=(parent.id,),
                    generation_method=f"genetic:{mutation.name}",
                    generation=generation,
                    metadata={"mutation": mutation.name},
                )
            except Exception:
                continue
            if candidate.structure_hash in existing:
                continue
            existing.add(candidate.structure_hash)
            offspring.append(candidate)
        return unique_candidates(offspring)


class SeedLibraryGenerator:
    def __init__(self, validator: CandidateValidator, psmiles: Sequence[str]) -> None:
        self.validator = validator
        self.psmiles = tuple(psmiles)

    def sample(self, count: int, *, random_seed: int = 42) -> list[PolymerCandidate]:
        rng = random.Random(random_seed)
        structures = list(self.psmiles)
        rng.shuffle(structures)
        candidates: list[PolymerCandidate] = []
        for psmiles in structures:
            try:
                candidates.append(self.validator.validate(psmiles))
            except Exception:
                continue
            if len(candidates) >= count:
                break
        return unique_candidates(candidates)
