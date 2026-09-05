#!/bin/sh
# Compile la lib native (emu2413 + shim) utilisee par le generateur.
set -e
cd "$(dirname "$0")"

case "$(uname -s)" in
  Darwin) EXT=dylib ;;
  *)      EXT=so    ;;
esac

mkdir -p build
cc -O2 -fPIC -shared \
   -I vendor/emu2413 \
   vendor/emu2413/emu2413.c native/shim.c \
   -o "build/libto8opll.$EXT" -lm

echo "OK -> build/libto8opll.$EXT"
