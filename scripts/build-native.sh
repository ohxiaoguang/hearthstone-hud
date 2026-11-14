#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo 'Native build requires Linux x86_64'; exit 1; }
cmake -S backend -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --parallel 2
build/native/hud-state-tests
mkdir -p bin licenses
cp build/native/hearthstone-hud-renderer bin/
chmod 755 bin/hearthstone-hud-renderer
cp build/native/_deps/glfw-src/LICENSE.md licenses/GLFW.txt
cp build/native/_deps/imgui-src/LICENSE.txt licenses/ImGui.txt
cp build/native/_deps/json-src/LICENSE.MIT licenses/nlohmann-json.txt
cp build/native/_deps/stb-src/LICENSE licenses/stb.txt
