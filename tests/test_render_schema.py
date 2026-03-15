"""tests/test_render_schema.py — Render-schema drift detection.

These tests cross-reference the Python schema tables in
``engine/render_schema.py`` against the actual dict-key strings
extracted from the C source files.  If a C file starts reading a key
that isn't declared in the schema (or vice-versa), a test fails.

The tests also exercise the validation helpers on synthetic dicts.
"""

from __future__ import annotations

import os
import re
import textwrap
from pathlib import Path

import pytest

from engine.render_schema import (
    RENDER_FRAME_REQUIRED,
    RENDER_FRAME_OPTIONAL,
    RENDER_ENTITIES_REQUIRED,
    RENDER_ENTITIES_OPTIONAL,
    RENDER_PARTICLES_REQUIRED,
    RENDER_PARTICLES_OPTIONAL,
    SSAO_REQUIRED,
    RenderSchemaError,
    validate_render_frame,
    validate_render_entities,
    validate_render_particles,
    validate_ssao,
    schema_keys_for,
    assert_required_keys,
)

# ── Helpers ──────────────────────────────────────────────────────

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"

# Regex for dict_get_*(dict, "key", ...) — required fields in C
_RE_REQUIRED = re.compile(
    r'dict_get_(?:double|int|buf(?:_rw)?)\s*\(\s*\w+\s*,\s*"([^"]+)"'
)
# Regex for PyDict_GetItemString(dict, "key") — optional fields in C
_RE_OPTIONAL = re.compile(
    r'PyDict_GetItemString\s*\(\s*\w+\s*,\s*"([^"]+)"'
)


def _c_keys(filename: str) -> tuple[set[str], set[str]]:
    """Return (required, optional) key sets extracted from a C source."""
    path = ENGINE_DIR / filename
    if not path.exists():
        pytest.skip(f"{filename} not found — C sources not in tree")
    src = path.read_text(encoding="utf-8", errors="replace")
    req = set(_RE_REQUIRED.findall(src))
    opt = set(_RE_OPTIONAL.findall(src))
    # Keys that appear in both patterns are required (dict_get_* wins)
    opt -= req
    return req, opt


def _schema_keys(
    required: list[tuple[str, str, str | None]],
    optional: list[tuple[str, str, str | None]],
) -> tuple[set[str], set[str]]:
    """Return (required, optional) key sets from a schema table pair."""
    return {k for k, _, _ in required}, {k for k, _, _ in optional}


# ── Drift detection: render_frame ────────────────────────────────

class TestRenderFrameDrift:
    """Ensure render_frame schema stays in sync with _ray_render.c."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.c_req, self.c_opt = _c_keys("_ray_render.c")
        self.s_req, self.s_opt = _schema_keys(
            RENDER_FRAME_REQUIRED, RENDER_FRAME_OPTIONAL
        )

    def test_no_c_required_missing_from_schema(self):
        missing = self.c_req - self.s_req
        assert not missing, (
            f"C requires these keys but schema doesn't list them as "
            f"required: {sorted(missing)}"
        )

    def test_no_c_optional_missing_from_schema(self):
        missing = self.c_opt - self.s_opt
        assert not missing, (
            f"C reads these optional keys but schema doesn't list them: "
            f"{sorted(missing)}"
        )

    def test_no_schema_required_absent_from_c(self):
        extra = self.s_req - self.c_req
        assert not extra, (
            f"Schema declares these as required but C never reads them: "
            f"{sorted(extra)}"
        )

    def test_no_schema_optional_absent_from_c(self):
        extra = self.s_opt - self.c_opt
        assert not extra, (
            f"Schema declares these as optional but C never reads them: "
            f"{sorted(extra)}"
        )


# ── Drift detection: render_entities ─────────────────────────────

class TestRenderEntitiesDrift:
    """Ensure render_entities schema stays in sync with _ray_entities.c."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.c_req, self.c_opt = _c_keys("_ray_entities.c")
        self.s_req, self.s_opt = _schema_keys(
            RENDER_ENTITIES_REQUIRED, RENDER_ENTITIES_OPTIONAL
        )
        # _ray_entities.c has *two* entry points: render_entities and
        # render_particles.  Split by the keys that belong to particles.
        ptcl_keys = {k for k, _, _ in RENDER_PARTICLES_REQUIRED} | {
            k for k, _, _ in RENDER_PARTICLES_OPTIONAL
        }
        # Remove particle-only keys from the entity comparison.
        particle_only = {"part_data", "n_particles", "dt", "gravity"}
        self.c_req -= particle_only
        self.c_opt -= particle_only

    def test_no_c_required_missing_from_schema(self):
        missing = self.c_req - self.s_req
        assert not missing, (
            f"C requires these keys but schema doesn't list them: "
            f"{sorted(missing)}"
        )

    def test_no_schema_required_absent_from_c(self):
        extra = self.s_req - self.c_req
        assert not extra, (
            f"Schema declares these as required but C never reads them: "
            f"{sorted(extra)}"
        )


# ── Validation smoke tests ──────────────────────────────────────

def _minimal_render_frame_ctx() -> dict:
    """Return a minimal valid render_frame context dict."""
    sw, sh = 320, 200
    mw, mh = 4, 4
    ts, nt = 64, 2
    ctx = {
        "fb": bytearray(sw * sh * 3),
        "zbuf": bytearray(sw * 8),
        "depth_px": bytearray(sw * sh * 4),
        "cam_x": 2.0, "cam_y": 2.0, "cam_angle": 0.0,
        "cam_fov": 1.0, "cam_h": 0.5, "horizon_shift": 0,
        "sw": sw, "sh": sh, "map_w": mw, "map_h": mh,
        "tex_size": ts, "num_tiles": nt, "is_interior": 1,
        "tiles": bytes(mh * mw * 4),
        "walls": bytes(mh * mw),
        "floor_h": bytes(mh * mw * 8),
        "ceil_h": bytes(mh * mw * 8),
        "floor_tex": bytes(mh * mw * 4),
        "ceil_tex": bytes(mh * mw * 4),
        "light": bytes(mh * mw * 8),
        "atlas": bytes(nt * ts * ts * 4),
        "fog_lut": bytes(256),
        "thin_lut": bytes(nt),
        "tall_lut": bytes(nt),
        "hs_lut": bytes(nt * 8),
        "trans_lut": bytes(nt),
        "alt_tex": bytes(nt * 4),
        "vscale": bytes(nt * 8),
        "anim_lut": bytes(nt * 4 * 4),
        "face_tex": bytes(mh * mw * 4 * 4),
        "overlay": bytes(0),
        "n_overlay": 0,
        "seg_off": bytes(mh * mw * 4 * 4),
        "seg_cnt": bytes(mh * mw * 4 * 4),
        "seg_tex": bytes(0),
        "seg_ytop": bytes(0),
        "n_total_segs": 0,
        "fstep_tex": bytes(mh * mw * 4 * 4),
        "cstep_tex": bytes(mh * mw * 4 * 4),
        "uwh": bytes(mh * mw * 8),
        "fstep_seg_off": bytes(mh * mw * 4 * 4),
        "fstep_seg_cnt": bytes(mh * mw * 4 * 4),
        "fstep_seg_tex": bytes(0),
        "fstep_seg_ytop": bytes(0),
        "n_fstep_segs": 0,
        "cstep_seg_off": bytes(mh * mw * 4 * 4),
        "cstep_seg_cnt": bytes(mh * mw * 4 * 4),
        "cstep_seg_tex": bytes(0),
        "cstep_seg_ytop": bytes(0),
        "n_cstep_segs": 0,
        "anim_tick": 0,
    }
    return ctx


class TestValidation:
    """Basic validation smoke tests."""

    def test_valid_render_frame_passes(self):
        ctx = _minimal_render_frame_ctx()
        validate_render_frame(ctx)  # should not raise

    def test_missing_required_key_raises(self):
        ctx = _minimal_render_frame_ctx()
        del ctx["cam_x"]
        with pytest.raises(RenderSchemaError, match="cam_x"):
            validate_render_frame(ctx)

    def test_wrong_type_raises(self):
        ctx = _minimal_render_frame_ctx()
        ctx["sw"] = "not_an_int"
        with pytest.raises(RenderSchemaError, match="sw"):
            validate_render_frame(ctx)

    def test_unknown_key_raises(self):
        ctx = _minimal_render_frame_ctx()
        ctx["nonexistent_key"] = 42
        with pytest.raises(RenderSchemaError, match="nonexistent_key"):
            validate_render_frame(ctx)

    def test_buffer_size_mismatch_raises(self):
        ctx = _minimal_render_frame_ctx()
        ctx["fb"] = bytearray(10)  # way too small
        with pytest.raises(RenderSchemaError, match="fb"):
            validate_render_frame(ctx)


class TestSchemaKeysFor:
    """Test the schema_keys_for introspection helper."""

    def test_render_frame_returns_all_keys(self):
        keys = schema_keys_for("render_frame")
        assert "cam_x" in keys
        assert "skybox" in keys  # optional key

    def test_render_entities(self):
        keys = schema_keys_for("render_entities")
        assert "ent_data" in keys
        assert "n_ents" in keys

    def test_unknown_entry_point_raises(self):
        with pytest.raises(KeyError):
            schema_keys_for("nonexistent")


class TestAssertRequiredKeys:
    """Test the always-on fast required-key check."""

    def test_passes_with_all_keys(self):
        ctx = _minimal_render_frame_ctx()
        # Should not raise
        assert_required_keys(ctx, "render_frame")

    def test_raises_on_missing_key(self):
        ctx = _minimal_render_frame_ctx()
        del ctx["cam_x"]
        with pytest.raises(RenderSchemaError, match="cam_x"):
            assert_required_keys(ctx, "render_frame")

    def test_raises_lists_all_missing(self):
        ctx = _minimal_render_frame_ctx()
        del ctx["cam_x"]
        del ctx["cam_y"]
        with pytest.raises(RenderSchemaError, match="cam_x.*cam_y|cam_y.*cam_x"):
            assert_required_keys(ctx, "render_frame")

    def test_render_entities_entry_point(self):
        """assert_required_keys supports the render_entities entry point."""
        # Just check that the entry-point name is recognized (no crash)
        with pytest.raises(RenderSchemaError):
            assert_required_keys({}, "render_entities")

    def test_render_particles_entry_point(self):
        with pytest.raises(RenderSchemaError):
            assert_required_keys({}, "render_particles")

    def test_ssao_entry_point(self):
        with pytest.raises(RenderSchemaError):
            assert_required_keys({}, "ssao_pass")

    def test_unknown_entry_point_raises_keyerror(self):
        with pytest.raises(KeyError):
            assert_required_keys({}, "nonexistent")

    def test_extra_keys_ignored(self):
        """Extra keys beyond required should not cause failures."""
        ctx = _minimal_render_frame_ctx()
        ctx["bonus_key"] = 42
        assert_required_keys(ctx, "render_frame")  # should not raise
