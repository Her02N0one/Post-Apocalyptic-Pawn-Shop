import json, collections
for zf in ["pawn_shop", "playground", "crossroads", "campsite", "outskirts", "house_interior"]:
    try:
        d = json.load(open(f"zones/{zf}.json"))
        ents = d.get("entities", [])
        chars = collections.Counter(e.get("char","?") for e in ents)
        print(f"{zf}: {len(ents)} entities  {dict(chars)}")
    except Exception as e:
        print(f"{zf}: {e}")
