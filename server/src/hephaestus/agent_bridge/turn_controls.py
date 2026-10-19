"""Immutable per-turn choices (INTERFACE.md §7A.10A), not session settings."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .model_selection import ModelSelectionError


class InteractionMode(StrEnum):
    MODELING = "modeling"
    PLAN = "plan"


class DfmMode(StrEnum):
    OFF = "off"
    GENERAL = "general"
    ADDITIVE = "additive"
    SHEET_METAL = "sheet_metal"
    MACHINING = "machining"
    CASTING = "casting"


class ThinkingLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class TurnControls:
    interaction_mode: InteractionMode = InteractionMode.MODELING
    dfm_mode: DfmMode = DfmMode.OFF
    thinking_level: ThinkingLevel = ThinkingLevel.MEDIUM

    def wire(self) -> dict[str, str]:
        return {
            "interaction_mode": self.interaction_mode.value,
            "dfm_mode": self.dfm_mode.value,
            "thinking_level": self.thinking_level.value,
        }


DEFAULT_TURN_CONTROLS = TurnControls()


def parse_turn_controls(body: Mapping[str, object]) -> TurnControls:
    """Read the three members of an already closed prompt body; null is invalid."""
    mode = body.get("interaction_mode", "modeling")
    dfm = body.get("dfm_mode", "off")
    effort = body.get("thinking_level", "medium")
    if not isinstance(mode, str) or not isinstance(dfm, str) or not isinstance(effort, str):
        raise ModelSelectionError("invalid_params")
    try:
        return TurnControls(InteractionMode(mode), DfmMode(dfm), ThinkingLevel(effort))
    except ValueError as exc:
        raise ModelSelectionError("invalid_params") from exc
