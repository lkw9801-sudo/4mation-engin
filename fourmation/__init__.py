"""4Mation rules engine and baseline bots."""
from .rules import (  # noqa: F401
    DEFAULT_RULES,
    P1,
    P2,
    RuleConfig,
    State,
    apply_move,
    legal_moves,
    new_game,
    parse_coord,
    to_coord,
)
