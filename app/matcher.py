import hashlib
import random
from typing import Dict, List, Optional, Set, Tuple


class MatchingError(Exception):
    """Raised when a valid single-cycle Secret Santa matching cannot be found."""


def find_single_cycle(
    participant_ids: List[int],
    excluded_pairs: List[Tuple[int, int]],
    seed: Optional[str] = None,
) -> List[int]:
    """
    Finds a single Hamiltonian cycle through all participant_ids such that:
    - Every participant gives one gift and receives one gift.
    - All participants form ONE single connected cycle (no A <-> B sub-loops).
    - No directed edge (u -> v) violates the excluded_pairs (symmetric or directed).
    Returns an ordered list [p0, p1, ..., p_{n-1}] where p_i gives to p_{(i+1) % n}.
    """
    n = len(participant_ids)
    if n < 3:
        raise MatchingError(
            "Det behövs minst 3 vuxna deltagare i huvudlottningen för att undvika att två personer bara byter med varandra (A ↔ B)."
        )

    rng = random.Random()
    if seed is not None and str(seed).strip() != "":
        seed_bytes = hashlib.sha256(str(seed).strip().encode("utf-8")).digest()
        rng.seed(int.from_bytes(seed_bytes, "big"))
    else:
        rng.seed()

    forbidden: Set[Tuple[int, int]] = set()
    for a, b in excluded_pairs:
        forbidden.add((a, b))
        forbidden.add((b, a))

    nodes = list(participant_ids)
    rng.shuffle(nodes)

    start = nodes[0]
    visited: Set[int] = {start}
    path: List[int] = [start]

    def backtrack(current: int) -> bool:
        if len(path) == n:
            # Check if last person can give to start without violating exclusions
            return (current, start) not in forbidden

        candidates = [u for u in nodes if u not in visited and (current, u) not in forbidden]
        rng.shuffle(candidates)
        for nxt in candidates:
            visited.add(nxt)
            path.append(nxt)
            if backtrack(nxt):
                return True
            path.pop()
            visited.remove(nxt)
        return False

    if not backtrack(start):
        raise MatchingError(
            "Kunde inte skapa en sammanhängande lottningskedja med nuvarande undantagsregler. "
            "Prova att ta bort något undantag eller lägg till fler deltagare."
        )

    return path


def assign_aliases(
    participant_ids: List[int],
    available_aliases: List[str],
    seed: Optional[str] = None,
) -> Dict[int, str]:
    """Assigns a unique random Swedish Christmas alias to each participant."""
    rng = random.Random()
    if seed is not None and str(seed).strip() != "":
        seed_bytes = hashlib.sha256(("alias:" + str(seed).strip()).encode("utf-8")).digest()
        rng.seed(int.from_bytes(seed_bytes, "big"))
    else:
        rng.seed()

    cleaned = [a.strip() for a in available_aliases if a.strip()]
    # Ensure we always have enough unique aliases
    fallback_adjectives = ["Glittrande", "Smygande", "Snöiga", "Mysiga", "Frostiga", "Gyllene", "Vintriga"]
    fallback_nouns = ["Tomten", "Renen", "Snögubben", "Pepparkakan", "Stjärnan", "Ugglan", "Räven"]
    while len(cleaned) < len(participant_ids):
        candidate = f"{rng.choice(fallback_adjectives)} {rng.choice(fallback_nouns)} #{len(cleaned) + 1}"
        if candidate not in cleaned:
            cleaned.append(candidate)

    pool = list(dict.fromkeys(cleaned))
    rng.shuffle(pool)
    return {pid: pool[i] for i, pid in enumerate(participant_ids)}
