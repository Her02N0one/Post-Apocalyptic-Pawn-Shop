"""logic/combat — Combat subpackage.

Modules
-------
attacks      — attack_entity, get_hitbox_targets, alert_nearby_faction,
               npc_melee_attack, npc_ranged_attack, get_entity_weapon_stats
engagement   — combat FSM brain (idle→chase→attack→flee→return)
movement     — velocity-producing combat movement behaviours
targeting    — target acquisition, LOS checks, ally-in-fire queries
damage       — apply_damage() + handle_death() pipeline
projectiles  — projectile_system() and helpers

Public symbols are re-exported here for ``from logic.combat import X``.
"""

# ── attacks ──────────────────────────────────────────────────────────
from logic.combat.attacks import (                   # noqa: F401
    attack_entity,
    get_hitbox_targets,
    alert_nearby_faction,
    get_entity_weapon_stats,
    npc_melee_attack,
    npc_ranged_attack,
)

# ── damage + death ───────────────────────────────────────────────────
from logic.combat.damage import apply_damage, handle_death  # noqa: F401
