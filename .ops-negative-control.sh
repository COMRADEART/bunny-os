#!/usr/bin/bash
# Negative control for the character checks.
#
# The three assertions that matter are "the legs are two shapes", "there is
# daylight between them" and "the silhouette loses half its ink at the hem".
# Restore the geometry the booted image was photographed with — a capsule torso
# reaching y=89 with the legs 11 apart — and they must all fail. A check that
# passes on the defect it was written for is worse than no check.
set -uo pipefail
sudo -u bunny -H bash <<'INNER'
set -uo pipefail
cd /home/bunny/bunny-os || exit 9
definition=shell/components/gnome-shell-extension/lib/character/definition.js
figure=shell/components/gnome-shell-extension/lib/character/figure.js
cp "${definition}" /tmp/definition.keep
cp "${figure}" /tmp/figure.keep

python3 - "${definition}" "${figure}" <<'PY'
import pathlib, sys
definition = pathlib.Path(sys.argv[1])
figure = pathlib.Path(sys.argv[2])

# The geometry from the run that was photographed and read as a robe.
text = definition.read_text(encoding="utf-8")
text = text.replace(
    "torso: {top: 38, hem: 78, topHalfWidth: 16.8, hemHalfWidth: 14.0},",
    "torso: {top: 41, hem: 89, topHalfWidth: 22.5, hemHalfWidth: 22.5},")
text = text.replace(
    "leg: {length: 55, thighWidth: 9.5, kneeWidth: 8.2, ankleWidth: 6.4, separation: 15},",
    "leg: {length: 43, thighWidth: 10.4, kneeWidth: 10.4, ankleWidth: 6.6, separation: 11},")
text = text.replace("hip: {y: 77.5, halfWidth: 12.0},", "hip: {y: 89, halfWidth: 14.5},")
definition.write_text(text, encoding="utf-8")

# And the drawing: a capsule torso, whose bottom is a semicircle.
body = figure.read_text(encoding="utf-8")
start = body.index("function drawTorso(")
end = body.index("\n/**", start)
body = body[:start] + """function drawTorso(cr, palette, g, pose) {
    const breathe = pose.breathe * 0.5;
    capsule(cr, 50, g.torso.top + 4, g.torso.hem,
        g.torso.topHalfWidth + breathe, g.torso.hemHalfWidth);
    setColour(cr, palette, 'hoodie');
    cr.fill();
}
""" + body[end:]
figure.write_text(body, encoding="utf-8")
print("geometry and torso reverted to the photographed robe")
PY

echo "=== the character checks against the robe ==="
python3 -m unittest tests.shell.test_desktop_shell.CharacterFigureTests 2>&1 | tail -22

cp /tmp/definition.keep "${definition}"
cp /tmp/figure.keep "${figure}"
echo "=== restored ==="
python3 -m unittest tests.shell.test_desktop_shell.CharacterFigureTests 2>&1 | tail -4
INNER
