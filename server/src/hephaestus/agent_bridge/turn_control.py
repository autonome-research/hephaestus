# Copyright 2026 The Hephaestus Authors
# SPDX-License-Identifier: Apache-2.0
"""Closed per-turn controls shared by HTTP, session routing, and the bridge."""

from __future__ import annotations

from typing import Final, Literal, TypeAlias

InteractionMode: TypeAlias = Literal["modeling", "plan"]
DfmMode: TypeAlias = Literal["off", "general", "additive", "sheet_metal", "machining", "casting"]
ThinkingLevel: TypeAlias = Literal["low", "medium", "high"]
EffectiveThinkingLevel: TypeAlias = Literal[
    "off", "minimal", "low", "medium", "high", "xhigh", "max"
]

INTERACTION_MODES: Final[tuple[InteractionMode, ...]] = ("modeling", "plan")
DFM_MODES: Final[tuple[DfmMode, ...]] = (
    "off",
    "general",
    "additive",
    "sheet_metal",
    "machining",
    "casting",
)
THINKING_LEVELS: Final[tuple[ThinkingLevel, ...]] = ("low", "medium", "high")
EFFECTIVE_THINKING_LEVELS: Final[tuple[EffectiveThinkingLevel, ...]] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)

DEFAULT_INTERACTION_MODE: Final[InteractionMode] = "modeling"
DEFAULT_DFM_MODE: Final[DfmMode] = "off"
DEFAULT_THINKING_LEVEL: Final[ThinkingLevel] = "medium"


def interaction_mode(value: object) -> InteractionMode:
    if not isinstance(value, str) or value not in INTERACTION_MODES:
        raise ValueError(f"interaction_mode must be one of {list(INTERACTION_MODES)}")
    return value


def dfm_mode(value: object) -> DfmMode:
    if not isinstance(value, str) or value not in DFM_MODES:
        raise ValueError(f"dfm_mode must be one of {list(DFM_MODES)}")
    return value


def thinking_level(value: object) -> ThinkingLevel:
    if not isinstance(value, str) or value not in THINKING_LEVELS:
        raise ValueError(f"thinking_level must be one of {list(THINKING_LEVELS)}")
    return value


def effective_thinking_level(value: object) -> EffectiveThinkingLevel | None:
    """Validate Pi's reported, capability-clamped level; ``None`` is legacy RPC."""
    if value is None:
        return None
    if not isinstance(value, str) or value not in EFFECTIVE_THINKING_LEVELS:
        raise ValueError(
            f"effective_thinking_level must be one of {list(EFFECTIVE_THINKING_LEVELS)}"
        )
    return value
