"""editor/entity_defs.py — Typed entity representation for the editor.

Replaces the ad-hoc ``list[dict]`` entity storage with strongly-typed
dataclasses.  Every component an entity can carry is a plain dataclass
with default values, making the schema explicit and IDE-friendly.

Zone JSON round-tripping:
    defs = [EntityDef.from_dict(d) for d in zone_data["entities"]]
    zone_data["entities"] = [e.to_dict() for e in defs]

ECS bridging (for play-testing from the editor):
    from editor.entity_defs import hydrate_to_ecs, snapshot_from_ecs
    hydrate_to_ecs(world, zone_name, defs)  # editor → runtime
    defs = snapshot_from_ecs(world, zone_name)  # runtime → editor
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar


# ─── Component-like dataclasses (editor-side, plain data) ───────────

@dataclass
class EDPosition:
    """World position (tiles)."""
    x: float = 0.0
    y: float = 0.0

@dataclass
class EDIdentity:
    """Display name and role."""
    name: str = ""
    kind: str = "npc"

@dataclass
class EDFacing:
    """Cardinal direction string."""
    direction: str = "down"

@dataclass
class EDSprite:
    """Visual glyph + colour + layer."""
    char: str = "?"
    color: list[int] = field(default_factory=lambda: [200, 200, 200])
    layer: int = 5

@dataclass
class EDCollider:
    """AABB collision box."""
    w: float = 0.6
    h: float = 0.6
    solid: bool = True

@dataclass
class EDHealth:
    """Hit points."""
    current: float = 100.0
    maximum: float = 100.0

@dataclass
class EDTileEntity:
    """Grid-snapped object (container, crop, ground_item)."""
    tile_type: str = "container"
    item_id: str = ""
    item_qty: int = 1
    loot_table: str = ""
    looted: bool = False

@dataclass
class EDWallSprite:
    """First-person wall-column rendering data."""
    texture_key: str = ""
    width: float = 1.0
    height: float = 1.0
    elevation: float = 0.0

@dataclass
class EDInventory:
    """Carried items: item_id → count."""
    items: dict[str, int] = field(default_factory=dict)

@dataclass
class EDDialogue:
    """NPC dialogue."""
    bark: str = ""

@dataclass
class EDCombatStats:
    """Combat parameters."""
    damage: float = 5.0
    attack_range: int = 1
    attack_cooldown: float = 2.0
    hostile: bool = False


# ─── Main entity definition ─────────────────────────────────────────

@dataclass
class EntityDef:
    """One entity in the editor — typed, inspectable, serialisable.

    Every optional component is ``None`` when not present.  This
    replaces the old ``dict`` with ``ent.get("health", {})`` guessing.
    """
    # Core identity (always present)
    id: str = ""
    prefab: str = ""

    # Components (None = not present on this entity)
    position: EDPosition = field(default_factory=EDPosition)
    identity: EDIdentity | None = None
    facing: EDFacing | None = None
    sprite: EDSprite | None = None
    collider: EDCollider | None = None
    health: EDHealth | None = None
    tile_entity: EDTileEntity | None = None
    wall_sprite: EDWallSprite | None = None
    inventory: EDInventory | None = None
    dialogue: EDDialogue | None = None
    combat_stats: EDCombatStats | None = None

    # Freeform extras (forge_archetype, dev_notes, tags, etc.)
    dev_notes: str = ""
    tags: list[str] = field(default_factory=list)
    forge_archetype: str = ""

    # ── Serialisation ───────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Convert to zone-JSON dict (same format as before)."""
        d: dict[str, Any] = {}
        if self.id:
            d["id"] = self.id
        if self.prefab:
            d["prefab"] = self.prefab

        # Position is always serialised
        d["position"] = {"x": self.position.x, "y": self.position.y}

        if self.identity is not None:
            d["identity"] = {
                "name": self.identity.name,
                "kind": self.identity.kind,
            }
        if self.facing is not None:
            d["facing"] = {"direction": self.facing.direction}

        if self.sprite is not None:
            d["sprite"] = {
                "char": self.sprite.char,
                "color": list(self.sprite.color),
                "layer": self.sprite.layer,
            }
        if self.collider is not None:
            d["collider"] = {
                "w": self.collider.w,
                "h": self.collider.h,
                "solid": self.collider.solid,
            }
        if self.health is not None:
            d["health"] = {
                "current": self.health.current,
                "maximum": self.health.maximum,
            }
        if self.tile_entity is not None:
            te: dict[str, Any] = {"tile_type": self.tile_entity.tile_type}
            if self.tile_entity.loot_table:
                te["loot_table"] = self.tile_entity.loot_table
            if self.tile_entity.tile_type == "ground_item":
                te["item_id"] = self.tile_entity.item_id
                te["item_qty"] = self.tile_entity.item_qty
            if self.tile_entity.looted:
                te["looted"] = True
            d["tile_entity"] = te

        if self.wall_sprite is not None:
            d["wall_sprite"] = {
                "texture_key": self.wall_sprite.texture_key,
                "width": self.wall_sprite.width,
                "height": self.wall_sprite.height,
                "elevation": self.wall_sprite.elevation,
            }
        if self.inventory is not None and self.inventory.items:
            d["inventory"] = {"items": dict(self.inventory.items)}

        if self.dialogue is not None and self.dialogue.bark:
            d["dialogue"] = {"bark": self.dialogue.bark}

        if self.combat_stats is not None:
            d["combat_stats"] = {
                "damage": self.combat_stats.damage,
                "attack_range": self.combat_stats.attack_range,
                "attack_cooldown": self.combat_stats.attack_cooldown,
                "hostile": self.combat_stats.hostile,
            }

        if self.dev_notes:
            d["dev_notes"] = self.dev_notes
        if self.tags:
            d["tags"] = list(self.tags)
        if self.forge_archetype:
            d["forge_archetype"] = self.forge_archetype

        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EntityDef":
        """Create from a zone-JSON entity dict."""
        ent = cls()
        ent.id = d.get("id", "")
        ent.prefab = d.get("prefab", "")

        pos = d.get("position", {})
        ent.position = EDPosition(
            x=float(pos.get("x", 0.0)),
            y=float(pos.get("y", 0.0)),
        )

        if "identity" in d:
            i = d["identity"]
            ent.identity = EDIdentity(
                name=i.get("name", ""),
                kind=i.get("kind", "npc"),
            )

        if "facing" in d:
            ent.facing = EDFacing(direction=d["facing"].get("direction", "down"))

        if "sprite" in d:
            s = d["sprite"]
            ent.sprite = EDSprite(
                char=s.get("char", "?"),
                color=list(s.get("color", [200, 200, 200])),
                layer=int(s.get("layer", 5)),
            )

        if "collider" in d:
            c = d["collider"]
            ent.collider = EDCollider(
                w=float(c.get("w", 0.6)),
                h=float(c.get("h", 0.6)),
                solid=bool(c.get("solid", True)),
            )

        if "health" in d:
            h = d["health"]
            ent.health = EDHealth(
                current=float(h.get("current", 100)),
                maximum=float(h.get("maximum", 100)),
            )

        if "tile_entity" in d:
            te = d["tile_entity"]
            ent.tile_entity = EDTileEntity(
                tile_type=te.get("tile_type", "container"),
                item_id=te.get("item_id", ""),
                item_qty=int(te.get("item_qty", 1)),
                loot_table=te.get("loot_table", ""),
                looted=bool(te.get("looted", False)),
            )

        if "wall_sprite" in d:
            ws = d["wall_sprite"]
            ent.wall_sprite = EDWallSprite(
                texture_key=ws.get("texture_key", ""),
                width=float(ws.get("width", 1.0)),
                height=float(ws.get("height", 1.0)),
                elevation=float(ws.get("elevation", 0.0)),
            )

        if "inventory" in d:
            inv = d["inventory"]
            ent.inventory = EDInventory(items=dict(inv.get("items", {})))

        if "dialogue" in d:
            dlg = d["dialogue"]
            ent.dialogue = EDDialogue(bark=dlg.get("bark", ""))

        if "combat_stats" in d:
            cs = d["combat_stats"]
            ent.combat_stats = EDCombatStats(
                damage=float(cs.get("damage", 5.0)),
                attack_range=int(cs.get("attack_range", 1)),
                attack_cooldown=float(cs.get("attack_cooldown", 2.0)),
                hostile=bool(cs.get("hostile", False)),
            )

        ent.dev_notes = d.get("dev_notes", "")
        raw_tags = d.get("tags", [])
        ent.tags = list(raw_tags) if isinstance(raw_tags, list) else []
        ent.forge_archetype = d.get("forge_archetype", "")

        return ent

    # ── Convenience ─────────────────────────────────────────────

    @property
    def display_name(self) -> str:
        """Readable label for UI."""
        if self.identity and self.identity.name:
            return self.identity.name
        return self.id or "unnamed"

    def add_component(self, comp_name: str) -> bool:
        """Add a default component by name.  Returns True if added."""
        _FACTORIES: dict[str, Any] = {
            "identity":     lambda: EDIdentity(),
            "facing":       lambda: EDFacing(),
            "sprite":       lambda: EDSprite(),
            "collider":     lambda: EDCollider(),
            "health":       lambda: EDHealth(),
            "tile_entity":  lambda: EDTileEntity(),
            "wall_sprite":  lambda: EDWallSprite(),
            "inventory":    lambda: EDInventory(),
            "dialogue":     lambda: EDDialogue(),
            "combat_stats": lambda: EDCombatStats(),
        }
        factory = _FACTORIES.get(comp_name)
        if factory is None:
            return False
        if getattr(self, comp_name, None) is not None:
            return False  # already present
        setattr(self, comp_name, factory())
        return True

    def remove_component(self, comp_name: str) -> bool:
        """Remove a component by name.  Returns True if removed."""
        if comp_name in ("position",):
            return False  # can't remove position
        if hasattr(self, comp_name) and getattr(self, comp_name) is not None:
            setattr(self, comp_name, None)
            return True
        return False

    COMPONENT_NAMES: ClassVar[list[str]] = [
        "identity", "facing", "sprite", "collider", "health",
        "tile_entity", "wall_sprite", "inventory", "dialogue",
        "combat_stats",
    ]

    def copy(self) -> "EntityDef":
        """Deep copy."""
        return deepcopy(self)
