"""logic/combat — Combat subpackage.

Modules
-------
allies       — shared ``iter_same_faction_allies()`` helper + ``PointProxy``
alerts       — sound alerts, intel sharing, faction alert propagation
attacks      — attack_entity, get_hitbox_targets, npc_melee_attack,
               npc_ranged_attack, get_entity_weapon_stats
damage       — apply_damage() + handle_death() pipeline
engagement   — combat FSM brain (idle→chase→attack→flee→return)
fireline     — fire-line awareness math + communication
melee_fsm    — melee attack sub-state-machine
movement     — velocity-producing combat movement behaviours
projectiles  — projectile_system() and helpers
tactical     — tactical position finding + LOS waypoint
targeting    — target acquisition, idle detection, ally queries

Public symbols are re-exported here for ``from logic.combat import X``.
"""

# ── attacks ──────────────────────────────────────────────────────────
from logic.combat.attacks import (                   # noqa: F401
    attack_entity,
    get_hitbox_targets,
    get_entity_weapon_stats,
    npc_melee_attack,
    npc_ranged_attack,
)

# ── alerts ───────────────────────────────────────────────────────────
from logic.combat.alerts import (                    # noqa: F401
    alert_nearby_faction,
    emit_combat_sound,
    share_combat_intel,
)

# ── damage + death ───────────────────────────────────────────────────
from logic.combat.damage import apply_damage, handle_death  # noqa: F401
