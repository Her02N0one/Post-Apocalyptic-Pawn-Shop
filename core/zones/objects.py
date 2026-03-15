"""core.zones.objects — Typed dict-compatible dataclasses for zone placeables.

Each zone placeable (quad, box, curve, portal, entity) is stored as a
dataclass that supports the **full dict protocol** used by the rest of the
codebase (``obj["key"]``, ``obj.get(key)``, ``"key" in obj``, etc.).

This means typed objects are transparent drop-in replacements for the
``dict[str, Any]`` values they supersede: existing editor tools,
renderer code, and serialisation paths continue to work unchanged.

``to_dict()`` / ``from_dict()`` provide explicit round-trip conversion
for persistence and legacy ffile interoperability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════
#  _DictBridge — dict-protocol mixin for dataclasses
# ═══════════════════════════════════════════════════════════════════

class _DictBridge:
    """Mixin giving a ``@dataclass`` dict-like access.

    Supported operations (matches the subset used by the PAPS codebase)::

        obj["key"]              # __getitem__
        obj["key"] = val        # __setitem__
        obj.get("key", default) # get
        "key" in obj            # __contains__
        obj.setdefault(k, v)    # setdefault
        dict(obj)               # via keys() + __getitem__
        obj.items()             # items
        for k in obj: ...       # __iter__
    """

    __slots__ = ()

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self.__dataclass_fields__:
            setattr(self, key, value)
        else:
            raise KeyError(f"Unknown field {key!r} on {type(self).__name__}")

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key in self.__dataclass_fields__

    def setdefault(self, key: str, default: Any = None) -> Any:
        """Return value for *key*; all dataclass fields always exist."""
        if key in self.__dataclass_fields__:
            return getattr(self, key)
        raise KeyError(f"Unknown field {key!r} on {type(self).__name__}")

    def keys(self) -> list[str]:
        return list(self.__dataclass_fields__)

    def values(self) -> list[Any]:
        return [getattr(self, k) for k in self.__dataclass_fields__]

    def items(self) -> list[tuple[str, Any]]:
        return [(k, getattr(self, k)) for k in self.__dataclass_fields__]

    def __iter__(self):
        return iter(self.__dataclass_fields__)

    def __len__(self) -> int:
        return len(self.__dataclass_fields__)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain ``dict`` suitable for msgpack."""
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


# ═══════════════════════════════════════════════════════════════════
#  Quad — two-sided flat decal / fence / barricade
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Quad(_DictBridge):
    """A two-sided textured quad (fence, poster, barricade).

    Fields match the actual dict keys read/written by editor tools and
    the renderer: ``x``, ``z`` (world-space), **not** the legacy
    ``cell`` + ``pos`` format.
    """
    uid: int = 0
    x: float = 0.0
    z: float = 0.0
    base_y: float = 0.0
    angle: float = 0.0
    width: float = 1.0
    height: float = 1.0
    texture: str = "brick_wall"
    collision: bool = False
    two_sided: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Quad:
        # Handle legacy cell/pos format
        if "cell" in d and "pos" in d and "x" not in d:
            cell = d.get("cell", [0, 0])
            pos = d.get("pos", [0.5, 0.5])
            x = float(cell[1]) + float(pos[0])
            z = float(cell[0]) + float(pos[1])
        else:
            x = float(d.get("x", 0.0))
            z = float(d.get("z", 0.0))
        return cls(
            uid=int(d.get("uid", 0)),
            x=x, z=z,
            base_y=float(d.get("base_y", 0.0)),
            angle=float(d.get("angle", 0.0)),
            width=float(d.get("width", 1.0)),
            height=float(d.get("height", 1.0)),
            texture=str(d.get("texture", "brick_wall")),
            collision=bool(d.get("collision", False)),
            two_sided=bool(d.get("two_sided", True)),
        )


# ═══════════════════════════════════════════════════════════════════
#  Box (Prism) — axis-aligned textured solid
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Box(_DictBridge):
    """An axis-aligned textured solid (prism / crate / pillar)."""
    uid: int = 0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0
    h: float = 1.0
    d: float = 1.0
    yaw: float = 0.0
    textures: dict[str, str] = field(default_factory=dict)
    collision: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Box:
        return cls(
            uid=int(d.get("uid", 0)),
            x=float(d.get("x", 0.0)),
            y=float(d.get("y", 0.0)),
            z=float(d.get("z", 0.0)),
            w=float(d.get("w", 1.0)),
            h=float(d.get("h", 1.0)),
            d=float(d.get("d", 1.0)),
            yaw=float(d.get("yaw", 0.0)),
            textures=dict(d.get("textures", {})),
            collision=bool(d.get("collision", False)),
        )


# ═══════════════════════════════════════════════════════════════════
#  Curve — cylindrical wall arc
# ═══════════════════════════════════════════════════════════════════

# Curve flag bit-field constants
CF_TRANSPARENT: int = 1  # bit 0 — see-through / alpha-blended surface


@dataclass
class Curve(_DictBridge):
    """A cylindrical wall arc (curved walls, pillars).

    ``flags`` is a bit-field.  Known bits:

    - ``CF_TRANSPARENT`` (1) — the surface is see-through.

    .. deprecated::
       The ``"transparent"`` JSON key is no longer emitted.
       Use ``flags & CF_TRANSPARENT`` instead.  Legacy data is
       auto-migrated by :func:`from_dict` and by the v1→v2 zone
       migration.
    """
    uid: int = 0
    cx: float = 0.0
    cy: float = 0.0
    radius: float = 1.0
    angle_start: float = 0.0
    angle_end: float = 90.0
    height_scale: float = 1.0
    base_y: float = 0.0
    texture: str = "brick_wall"
    flags: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Curve:
        flags = int(d.get("flags", 0))
        # Legacy migration: absorb "transparent" → CF_TRANSPARENT bit
        if d.get("transparent", False):
            flags |= CF_TRANSPARENT
        return cls(
            uid=int(d.get("uid", 0)),
            cx=float(d.get("cx", 0.0)),
            cy=float(d.get("cy", 0.0)),
            radius=float(d.get("radius", 1.0)),
            angle_start=float(d.get("angle_start", 0.0)),
            angle_end=float(d.get("angle_end", 90.0)),
            height_scale=float(d.get("height_scale", 1.0)),
            base_y=float(d.get("base_y", 0.0)),
            texture=str(d.get("texture", "brick_wall")),
            flags=flags,
        )


# ═══════════════════════════════════════════════════════════════════
#  RenderPortal — same-zone non-Euclidean portal
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RenderPortal(_DictBridge):
    """A same-zone non-Euclidean portal surface."""
    uid: int = 0
    cell: list[int] = field(default_factory=lambda: [0, 0])
    face: int = 0
    dest_x: float = 0.0
    dest_y: float = 0.0
    angle_offset: float = 0.0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RenderPortal:
        return cls(
            uid=int(d.get("uid", 0)),
            cell=list(d.get("cell", [0, 0])),
            face=int(d.get("face", 0)),
            dest_x=float(d.get("dest_x", 0.0)),
            dest_y=float(d.get("dest_y", 0.0)),
            angle_offset=float(d.get("angle_offset", 0.0)),
        )


# ═══════════════════════════════════════════════════════════════════
#  EntityDescriptor — typed entity spawn data (extended dict bridge)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class EntityDescriptor(_DictBridge):
    """A typed entity spawn descriptor.

    Fields match the actual keys used by default editor-created entities:
    ``type``, ``x``, ``y``, ``angle``, ``state``, ``overrides``.

    The ``extra`` dict absorbs any additional keys (legacy ``position``,
    ``sprite``, ``prefab``, ``tile_entity``, ``facing``, etc.) so they
    are preserved through load/save and accessible via ``ent.get(key)``.

    ``extra`` is NOT exposed as a top-level key — its contents are merged
    into the object's key namespace, so ``ent["sprite"]`` hits ``extra``
    transparently.
    """
    uid: int = 0
    id: str = ""
    type: str = ""
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0
    state: str = "default"
    overrides: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict, repr=False)

    # ── Override _DictBridge to merge ``extra`` transparently ──────

    def __getitem__(self, key: str) -> Any:
        if key in self.__dataclass_fields__ and key != "extra":
            return getattr(self, key)
        if key in self.extra:
            return self.extra[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self.__dataclass_fields__ and key != "extra":
            setattr(self, key, value)
        else:
            self.extra[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        if key in self.__dataclass_fields__ and key != "extra":
            return True
        return key in self.extra

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key in self.__dataclass_fields__ and key != "extra":
            return getattr(self, key)
        return self.extra.setdefault(key, default)

    def pop(self, key: str, *args: Any) -> Any:
        if key in self.extra:
            return self.extra.pop(key)
        if args:
            return args[0]
        raise KeyError(key)

    def keys(self) -> list[str]:
        base = [k for k in self.__dataclass_fields__ if k != "extra"]
        return base + list(self.extra.keys())

    def values(self) -> list[Any]:
        return [self[k] for k in self.keys()]

    def items(self) -> list[tuple[str, Any]]:
        return [(k, self[k]) for k in self.keys()]

    def __iter__(self):
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self.__dataclass_fields__) - 1 + len(self.extra)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        for k in self.__dataclass_fields__:
            if k == "extra":
                continue
            v = getattr(self, k)
            d[k] = dict(v) if isinstance(v, dict) else v
        d.update(self.extra)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EntityDescriptor:
        _KNOWN = {"uid", "id", "type", "x", "y", "angle", "state", "overrides"}
        extra = {k: v for k, v in d.items() if k not in _KNOWN}

        # Legacy "prefab" → "type"
        etype = d.get("type", "")
        if not etype:
            etype = extra.pop("prefab", "")

        # Legacy "position" dict → flat x/y
        x = float(d.get("x", 0.0))
        y = float(d.get("y", 0.0))
        pos = extra.get("position")
        if isinstance(pos, dict):
            x = float(pos.get("x", x))
            y = float(pos.get("y", y))

        return cls(
            uid=int(d.get("uid", 0)),
            id=str(d.get("id", "")),
            type=etype,
            x=x, y=y,
            angle=float(d.get("angle", 0.0)),
            state=str(d.get("state", "default")),
            overrides=dict(d.get("overrides", {})),
            extra=extra,
        )


# ═══════════════════════════════════════════════════════════════════
#  Conversion helpers
# ═══════════════════════════════════════════════════════════════════

def dicts_to_quads(dicts: list[dict]) -> list[Quad]:
    return [Quad.from_dict(d) for d in dicts]

def quads_to_dicts(quads: list[Quad]) -> list[dict]:
    return [q.to_dict() for q in quads]

def dicts_to_boxes(dicts: list[dict]) -> list[Box]:
    return [Box.from_dict(d) for d in dicts]

def boxes_to_dicts(boxes: list[Box]) -> list[dict]:
    return [b.to_dict() for b in boxes]

def dicts_to_curves(dicts: list[dict]) -> list[Curve]:
    return [Curve.from_dict(d) for d in dicts]

def curves_to_dicts(curves: list[Curve]) -> list[dict]:
    return [c.to_dict() for c in curves]

def dicts_to_render_portals(dicts: list[dict]) -> list[RenderPortal]:
    return [RenderPortal.from_dict(d) for d in dicts]

def render_portals_to_dicts(portals: list[RenderPortal]) -> list[dict]:
    return [p.to_dict() for p in portals]

def dicts_to_entities(dicts: list[dict]) -> list[EntityDescriptor]:
    return [EntityDescriptor.from_dict(d) for d in dicts]

def entities_to_dicts(entities: list[EntityDescriptor]) -> list[dict]:
    return [e.to_dict() for e in entities]


def serialize_objects(objs: list) -> list[dict]:
    """Convert a mixed list of typed objects and/or dicts to plain dicts.

    Safe to call on already-plain dicts (returns a shallow copy).
    Used by io.py before msgpack serialisation.
    """
    return [dict(o) for o in objs]
