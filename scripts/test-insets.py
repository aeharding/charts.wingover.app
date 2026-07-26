import json
import sys

sys.path.insert(0, "/repo/scripts")
import derive

fails = 0
for e in json.load(open("/repo/insets.json")):
    try:
        box = derive.detect_inset(e["sheet"], *e["seed"])
        print(f"OK   {e['sheet']:14} [{box[0]:.3f}, {box[1]:.3f}, {box[2]:.3f}, {box[3]:.3f}]  {e['note']}")
    except RuntimeError as err:
        fails += 1
        print(f"FAIL {e['sheet']:14} seed {e['seed']}  {e['note']}")
print("failures:", fails)
