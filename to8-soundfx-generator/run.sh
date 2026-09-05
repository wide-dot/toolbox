#!/bin/sh
# Lance l'interface web du generateur.
cd "$(dirname "$0")"
exec python3 cli.py ui "$@"
