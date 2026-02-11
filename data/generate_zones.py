"""data/generate_zones.py — Generate the 3 playable zone NBT files.

Run once:  python data/generate_zones.py

Creates:
  zones/settlement.nbt  (40×40)
  zones/road.nbt        (60×20)
  zones/ruins.nbt       (40×40)
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.nbt import save_zone_nbt

# Tile IDs (from core/constants.py)
VOID  = 0
GRASS = 1
DIRT  = 2
STONE = 3
WATER = 4
WOOD  = 5
WALL  = 6
TELE  = 9     # teleporter
SAND  = 7     # new: sandy ground
RUBBLE = 8    # new: rubble / debris

# ═════════════════════════════════════════════════════════════════════
#  SETTLEMENT  40×40
# ═════════════════════════════════════════════════════════════════════

def make_settlement():
    W, H = 40, 40
    tiles = [[GRASS] * W for _ in range(H)]

    # ── Perimeter wall ──
    for r in range(H):
        for c in range(W):
            if r == 0 or r == H-1 or c == 0 or c == W-1:
                tiles[r][c] = WALL

    # ── Gate opening (top wall center) — teleporter to road ──
    for c in range(18, 22):
        tiles[0][c] = DIRT      # open the wall
    tiles[0][19] = TELE         # teleporter tile
    tiles[0][20] = TELE

    # ── Main dirt road from gate down to market ──
    for r in range(1, 22):
        tiles[r][19] = DIRT
        tiles[r][20] = DIRT

    # ── Market square (center) — stone floor ──
    for r in range(18, 26):
        for c in range(16, 25):
            tiles[r][c] = STONE
    # Market stalls (walls inside square)
    for c in range(17, 24, 3):
        tiles[19][c] = WALL
        tiles[24][c] = WALL

    # ── Farm area (left side) ──
    for r in range(5, 16):
        for c in range(3, 14):
            tiles[r][c] = DIRT
    # Crop rows
    for r in range(6, 15):
        for c in range(4, 13, 2):
            tiles[r][c] = GRASS  # alternating crop / dirt

    # ── Well (center-left, between farm and market) ──
    tiles[16][10] = WATER
    tiles[16][11] = WATER
    tiles[17][10] = WATER
    tiles[17][11] = WATER
    for r in range(15, 19):
        for c in range(9, 13):
            if tiles[r][c] != WATER:
                tiles[r][c] = STONE

    # ── Residential area (bottom-left) ──
    # House 1
    for r in range(28, 33):
        for c in range(3, 10):
            if r == 28 or r == 32 or c == 3 or c == 9:
                tiles[r][c] = WALL
            else:
                tiles[r][c] = WOOD
    tiles[32][6] = WOOD  # door

    # House 2
    for r in range(28, 33):
        for c in range(12, 18):
            if r == 28 or r == 32 or c == 12 or c == 17:
                tiles[r][c] = WALL
            else:
                tiles[r][c] = WOOD
    tiles[32][15] = WOOD  # door

    # ── Storehouse (bottom-right) ──
    for r in range(28, 36):
        for c in range(26, 37):
            if r == 28 or r == 35 or c == 26 or c == 36:
                tiles[r][c] = WALL
            else:
                tiles[r][c] = WOOD
    tiles[28][31] = WOOD  # door (north side)

    # ── Paths connecting areas ──
    # Farm to well
    for c in range(10, 20):
        tiles[16][c] = DIRT
    # Market to storehouse
    for c in range(24, 31):
        tiles[25][c] = DIRT
    for r in range(25, 28):
        tiles[r][30] = DIRT
    # Market to residential
    for r in range(25, 28):
        tiles[r][15] = DIRT

    # Teleporter targets from road zone
    teleporters = {
        (0, 19): {"zone": "road", "r": 18, "c": 1},
        (0, 20): {"zone": "road", "r": 18, "c": 2},
    }

    anchor = (20.0, 20.0)  # Market square center

    save_zone_nbt("settlement", tiles, anchor, teleporters)
    print(f"  settlement.nbt  {W}×{H}  teleporters={len(teleporters)}")


# ═════════════════════════════════════════════════════════════════════
#  ROAD  60×20
# ═════════════════════════════════════════════════════════════════════

def make_road():
    W, H = 60, 20
    tiles = [[GRASS] * W for _ in range(H)]

    # ── Edges are rougher terrain ──
    for r in range(H):
        tiles[r][0] = WALL
        tiles[r][W-1] = WALL
    for c in range(W):
        tiles[0][c] = WALL
        tiles[H-1][c] = WALL

    # ── Main road (horizontal, center band) ──
    for r in range(8, 12):
        for c in range(1, W-1):
            tiles[r][c] = DIRT

    # ── Settlement connection (left side) — teleporter ──
    for r in range(7, 13):
        tiles[r][1] = DIRT
    tiles[9][1] = TELE
    tiles[10][1] = TELE

    # ── Ruins connection (right side) — teleporter ──
    for r in range(7, 13):
        tiles[r][W-2] = DIRT
    tiles[9][W-2] = TELE
    tiles[10][W-2] = TELE

    # ── Crossroads (center) — path goes north/south ──
    cross_c = 30
    for r in range(1, H-1):
        tiles[r][cross_c] = DIRT
        tiles[r][cross_c+1] = DIRT
    # Small marker stones at crossroads
    tiles[7][cross_c-1] = STONE
    tiles[7][cross_c+2] = STONE
    tiles[12][cross_c-1] = STONE
    tiles[12][cross_c+2] = STONE

    # ── Hidden cache — off the south path from crossroads ──
    for r in range(13, 18):
        tiles[r][cross_c] = GRASS  # overgrown path
    # Small ruined structure
    for r in range(15, 18):
        for c in range(28, 33):
            if r == 15 or r == 17 or c == 28 or c == 32:
                tiles[r][c] = WALL
            else:
                tiles[r][c] = WOOD
    tiles[17][30] = DIRT  # collapsed door

    # ── Scattered debris along road ──
    import random
    random.seed(42)
    for _ in range(15):
        r = random.randint(2, H-3)
        c = random.randint(5, W-6)
        if tiles[r][c] == GRASS:
            tiles[r][c] = STONE  # rocks

    # ── Abandoned car (stone blocks) ──
    for r in range(4, 6):
        for c in range(15, 19):
            tiles[r][c] = STONE
    for r in range(4, 6):
        for c in range(42, 45):
            tiles[r][c] = STONE

    teleporters = {
        (9, 1):    {"zone": "settlement", "r": 1, "c": 19},
        (10, 1):   {"zone": "settlement", "r": 1, "c": 20},
        (9, W-2):  {"zone": "ruins", "r": 20, "c": 1},
        (10, W-2): {"zone": "ruins", "r": 20, "c": 2},
    }

    anchor = (30.0, 10.0)  # Crossroads

    save_zone_nbt("road", tiles, anchor, teleporters)
    print(f"  road.nbt        {W}×{H}  teleporters={len(teleporters)}")


# ═════════════════════════════════════════════════════════════════════
#  RUINS  40×40
# ═════════════════════════════════════════════════════════════════════

def make_ruins():
    W, H = 40, 40
    tiles = [[DIRT] * W for _ in range(H)]

    # ── Perimeter ──
    for r in range(H):
        tiles[r][0] = WALL
        tiles[r][W-1] = WALL
    for c in range(W):
        tiles[0][c] = WALL
        tiles[H-1][c] = WALL

    # ── Entrance (left wall) — teleporter to road ──
    for r in range(18, 23):
        tiles[r][1] = DIRT
    tiles[20][1] = TELE
    tiles[21][1] = TELE

    # ── Path from entrance inward ──
    for c in range(1, 15):
        tiles[20][c] = STONE
        tiles[21][c] = STONE

    # ── Collapsed building (center-left) ──
    for r in range(12, 20):
        for c in range(8, 18):
            if r == 12 or r == 19:
                tiles[r][c] = WALL
            elif c == 8 or c == 17:
                tiles[r][c] = WALL
            else:
                tiles[r][c] = STONE
    # Collapsed sections (gaps in walls)
    tiles[12][12] = STONE
    tiles[12][13] = STONE
    tiles[19][10] = STONE
    tiles[15][8] = STONE
    tiles[16][17] = STONE
    # Interior rubble
    tiles[14][11] = WALL
    tiles[15][13] = WALL
    tiles[17][10] = WALL

    # ── Raider camp (upper right) ──
    for r in range(3, 12):
        for c in range(25, 37):
            tiles[r][c] = DIRT
    # Campfire
    tiles[7][30] = STONE
    tiles[7][31] = STONE
    tiles[8][30] = STONE
    tiles[8][31] = STONE
    # Tent structures (partial walls)
    for r in range(4, 7):
        tiles[r][26] = WALL
    for c in range(26, 30):
        tiles[4][c] = WALL
    tiles[5][27] = WOOD
    tiles[5][28] = WOOD
    # Another tent
    for r in range(4, 7):
        tiles[r][34] = WALL
    for c in range(32, 35):
        tiles[4][c] = WALL
    tiles[5][33] = WOOD

    # ── Deep ruins (bottom right) ── 
    for r in range(27, 38):
        for c in range(22, 38):
            tiles[r][c] = STONE
    # Overgrown walls
    for r in range(28, 37):
        tiles[r][22] = WALL
        tiles[r][37] = WALL
    for c in range(22, 38):
        tiles[27][c] = WALL
        tiles[37][c] = WALL
    # Openings
    tiles[27][28] = STONE
    tiles[27][29] = STONE
    tiles[37][30] = STONE
    # Interior rooms
    for c in range(29, 38):
        tiles[32][c] = WALL
    tiles[32][33] = STONE  # doorway

    # ── Pharmacy (inside deep ruins, lower-right corner) ──
    for r in range(33, 37):
        for c in range(30, 37):
            tiles[r][c] = WOOD
    # Shelving
    tiles[34][31] = WALL
    tiles[34][35] = WALL
    tiles[35][33] = WALL

    # ── Scattered rubble throughout ──
    import random
    random.seed(99)
    for _ in range(40):
        r = random.randint(2, H-3)
        c = random.randint(2, W-3)
        if tiles[r][c] == DIRT:
            tiles[r][c] = STONE

    teleporters = {
        (20, 1): {"zone": "road", "r": 9, "c": 57},
        (21, 1): {"zone": "road", "r": 10, "c": 57},
    }

    anchor = (10.0, 20.0)  # Near entrance

    save_zone_nbt("ruins", tiles, anchor, teleporters)
    print(f"  ruins.nbt       {W}×{H}  teleporters={len(teleporters)}")


# ═════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Generating zone NBT files...")
    make_settlement()
    make_road()
    make_ruins()
    print("Done! Files written to zones/")
