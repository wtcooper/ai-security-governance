"""Proposing a fixed, representative core sample set for a benchmark.

Why this exists: a run that draws "the first N" samples is deterministic but arbitrary
(the head of a dataset is often clustered — one language, one category), and a random draw
per run makes results incomparable between runs. The governance answer is an explicit list
of sample ids, stored in the versioned policy, so every run measures exactly the same cases
and changing the set is a visible policy event.

Selection is stratified and seeded:

* Ids are grouped by their stratum (a dataset metadata value, e.g. `injection_variant`);
  unstratified datasets form one group.
* The requested size is allocated proportionally across strata by largest remainder, so the
  core set mirrors the dataset's composition instead of over-representing its head.
* Within each stratum, ids are sorted and drawn with a deterministic seeded RNG. Same seed,
  same size, same dataset ⇒ the same ids, every time, on every machine.

The output is a PROPOSAL. Nothing changes until it is saved into a new policy version.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class CoreSetProposal:
    sample_ids: list[str]
    # stratum -> how many of its samples were selected / how many exist.
    allocation: dict[str, tuple[int, int]]
    seed: str
    size: int


def propose_core_set(
    ids: list[str],
    id_strata: dict[str, str],
    size: int,
    seed: str,
) -> CoreSetProposal:
    if size < 1:
        raise ValueError("core set size must be at least 1")
    unique_ids = sorted(set(ids))
    if size > len(unique_ids):
        raise ValueError(f"core set size {size} exceeds dataset size {len(unique_ids)}")

    # Group by stratum. Ids without a stratum label share one bucket, which also covers the
    # entirely unstratified case.
    strata: dict[str, list[str]] = {}
    for sample_id in unique_ids:
        strata.setdefault(id_strata.get(sample_id, "all"), []).append(sample_id)

    # Largest-remainder allocation, so proportions survive integer rounding and the total
    # comes out exactly to `size`. Ties break on stratum name for determinism.
    total = len(unique_ids)
    quotas = {name: size * len(members) / total for name, members in strata.items()}
    counts = {name: int(quota) for name, quota in quotas.items()}
    remainder = size - sum(counts.values())
    by_fraction = sorted(
        strata, key=lambda name: (-(quotas[name] - counts[name]), name)
    )
    for name in by_fraction[:remainder]:
        counts[name] += 1
    # Rounding can allocate a stratum more than it holds; hand the excess to the largest
    # strata that still have room.
    for name in sorted(counts, key=lambda n: (len(strata[n]), n)):
        excess = counts[name] - len(strata[name])
        if excess > 0:
            counts[name] = len(strata[name])
            for other in sorted(strata, key=lambda n: -len(strata[n])):
                room = len(strata[other]) - counts[other]
                take = min(room, excess)
                counts[other] += take
                excess -= take
                if excess == 0:
                    break

    selected: list[str] = []
    allocation: dict[str, tuple[int, int]] = {}
    for name in sorted(strata):
        members = strata[name]  # already sorted: built from sorted unique_ids
        take = counts.get(name, 0)
        allocation[name] = (take, len(members))
        if take:
            # Per-stratum RNG: adding or removing one stratum never reshuffles the others.
            rng = random.Random(f"{seed}:{name}")
            selected.extend(rng.sample(members, take))

    return CoreSetProposal(
        sample_ids=sorted(selected), allocation=allocation, seed=seed, size=size
    )
