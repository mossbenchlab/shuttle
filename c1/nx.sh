#!/bin/bash
# usage: nx.sh cell ms tools [...]  -> processes replies; a cell is reported MORE only if `pre` passes
cd "$(dirname "$0")"
while [ $# -gt 0 ]; do
  python3 c1.py next $1 $2 $3 >/dev/null 2>&1
  g=$(python3 c1.py grade $1 | tr -d '\n ' | grep -o '"complete":[a-z]*,"end":[^,]*,"replies":[0-9]*,"seconds":[0-9.]*' | sed 's/"//g; s/seconds:\([0-9]*\.[0-9]\)[0-9]*/sec:\1/')
  if python3 c1.py pre $1 >/dev/null 2>&1; then echo "MORE(pre OK) $1  $g"; else if echo "$g" | grep -q "end:null"; then echo "BLOCKED(pre failed) $1  $g"; else echo "FIN  $1  $g"; fi; fi
  shift 3
done
