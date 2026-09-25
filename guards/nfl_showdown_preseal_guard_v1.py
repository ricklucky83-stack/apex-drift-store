from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from hashlib import sha256
import json


class PresealViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class SDLineup:
    captain: str
    flex: tuple[str, str, str, str, str]
    flex_salary: dict[str, int]
    script_family: str | None = None

    @property
    def players(self) -> tuple[str, ...]:
        return (self.captain, *self.flex)

    def salary(self) -> int:
        if self.captain not in self.flex_salary:
            raise PresealViolation(f"missing salary for captain={self.captain}")
        if len(set(self.players)) != 6:
            raise PresealViolation("duplicate player inside lineup")
        missing = [p for p in self.players if p not in self.flex_salary]
        if missing:
            raise PresealViolation(f"missing salaries={missing}")
        return int(round(self.flex_salary[self.captain] * 1.5)) + sum(
            self.flex_salary[p] for p in self.flex
        )

    def identity(self) -> tuple[str, tuple[str, ...]]:
        return self.captain, tuple(sorted(self.flex))


REQUIRED_PROVENANCE = {
    "engine_version",
    "bundle_sha256",
    "engine_sha256",
    "selector_id",
    "mc_worlds",
    "public_field_sims",
    "machine_receipt_sha256",
}


def _require_provenance(receipt: dict) -> None:
    missing = sorted(REQUIRED_PROVENANCE - set(receipt))
    if missing:
        raise PresealViolation(f"missing execution provenance={missing}")
    if int(receipt["mc_worlds"]) <= 0:
        raise PresealViolation("mc_worlds must be > 0")
    if int(receipt["public_field_sims"]) <= 0:
        raise PresealViolation("public_field_sims must be > 0")
    for key in ("bundle_sha256", "engine_sha256", "machine_receipt_sha256"):
        value = str(receipt[key]).lower()
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise PresealViolation(f"invalid sha256 field={key}")


def preseal_nfl_showdown(
    lineups: list[SDLineup],
    receipt: dict,
    requested_entries: int,
    *,
    min_salary: int = 40000,
    max_salary: int = 50000,
    min_captains_large_board: int = 4,
    min_script_families_large_board: int = 4,
    max_three_player_core_share: float = 0.85,
) -> dict:
    """
    Fail-closed preseal gate for NFL DraftKings Showdown.

    This gate does not select lineups. It validates the engine-owned output and
    refuses to seal a board when salary math, provenance, uniqueness, requested
    board size, or championship-world coverage are not proven.
    """
    _require_provenance(receipt)

    if requested_entries < 1:
        raise PresealViolation("requested_entries must be positive")
    if len(lineups) != requested_entries:
        raise PresealViolation(
            f"board size mismatch: got={len(lineups)} requested={requested_entries}"
        )

    identities = [x.identity() for x in lineups]
    if len(set(identities)) != len(identities):
        raise PresealViolation("duplicate exact lineups detected")

    salaries = []
    for i, lu in enumerate(lineups, 1):
        sal = lu.salary()
        salaries.append(sal)
        if sal > max_salary:
            raise PresealViolation(f"lineup {i} over cap: {sal}>{max_salary}")
        if sal < min_salary:
            raise PresealViolation(f"lineup {i} under floor: {sal}<{min_salary}")

    captains = Counter(x.captain for x in lineups)
    scripts = Counter(x.script_family for x in lineups if x.script_family)

    if requested_entries >= 40:
        if len(captains) < min_captains_large_board:
            raise PresealViolation(
                f"insufficient CPT coverage: {len(captains)}<{min_captains_large_board}"
            )
        if len(scripts) < min_script_families_large_board:
            raise PresealViolation(
                f"missing championship-script coverage: {len(scripts)}"
                f"<{min_script_families_large_board}"
            )

        core_counts: Counter[tuple[str, str, str]] = Counter()
        for lu in lineups:
            players = sorted(lu.players)
            for i in range(len(players) - 2):
                for j in range(i + 1, len(players) - 1):
                    for k in range(j + 1, len(players)):
                        core_counts[(players[i], players[j], players[k])] += 1
        top_core, top_count = core_counts.most_common(1)[0]
        top_share = top_count / requested_entries
        override = receipt.get("concentration_override")
        if top_share > max_three_player_core_share and not override:
            raise PresealViolation(
                f"portfolio cannibalization: core={top_core} share={top_share:.3f}"
                f">{max_three_player_core_share:.3f}"
            )

    canonical = {
        "requested_entries": requested_entries,
        "salary_min": min(salaries),
        "salary_max": max(salaries),
        "captain_exposure": dict(captains),
        "script_family_exposure": dict(scripts),
        "execution": {k: receipt[k] for k in sorted(REQUIRED_PROVENANCE)},
    }
    canonical_bytes = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    canonical["preseal_receipt_sha256"] = sha256(canonical_bytes).hexdigest()
    canonical["status"] = "PRESEAL_PASS"
    return canonical
