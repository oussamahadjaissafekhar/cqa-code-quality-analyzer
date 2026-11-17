#!/bin/sh
# Forward every argument to the installed CLI. `exec` keeps signal handling
# (including Ctrl+C -> exit 130) intact instead of adding an extra shell.
set -eu
exec cqa "$@"
