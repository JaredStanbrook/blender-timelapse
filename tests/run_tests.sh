#!/usr/bin/env bash
# Build the extension, install it into a throwaway Blender profile and run all tests.
# Usage: tests/run_tests.sh /path/to/blender
set -euo pipefail
BLENDER=${1:-blender}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-$(mktemp -d)}
export HOME="$WORK/home"            # isolated user config / extensions
rm -rf "$WORK/out_bg" "$WORK/out_gui" "$WORK/out_quit"
mkdir -p "$HOME" "$WORK/out_bg" "$WORK/out_gui" "$ROOT/dist"

"$BLENDER" --command extension validate "$ROOT/blender_timelapse"
"$BLENDER" --command extension build --source-dir "$ROOT/blender_timelapse" --output-dir "$ROOT/dist"
ZIP=$(ls "$ROOT"/dist/blender_timelapse-*.zip | tail -1)
"$BLENDER" --command extension install-file -r user_default -e "$ZIP"

status=0
xvfb-run -a -s "-screen 0 1600x1000x24" "$BLENDER" -b --python "$ROOT/tests/test_background.py" \
    -- "$WORK/out_bg" "$WORK/report_background.json" || status=1
xvfb-run -a -s "-screen 0 1600x1000x24" "$BLENDER" --python "$ROOT/tests/test_gui.py" \
    -- "$WORK/out_gui" "$WORK/report_gui.json" || status=1
xvfb-run -a -s "-screen 0 1600x1000x24" "$BLENDER" --python "$ROOT/tests/test_quit.py" -- "$WORK/out_quit" || true
python3 - "$WORK/out_quit/Quit/Session_001/session_info.json" <<'PY' || status=1
import json, sys
m = json.load(open(sys.argv[1]))
ok = m["status"] == "stopped" and m["ended"] and m["frames"] >= 2
print(("PASS" if ok else "FAIL") + " quit mid-recording closes session:", m["status"], m["end_reason"], m["frames"])
sys.exit(0 if ok else 1)
PY
# The GUI run always exits 0 (it quits itself); judge it by its report.
python3 -c "import json,sys; r=json.load(open(sys.argv[1])); sys.exit(any(not t['passed'] for t in r) or not r)" \
    "$WORK/report_gui.json" || status=1
echo "Reports: $WORK/report_background.json $WORK/report_gui.json"
exit $status
