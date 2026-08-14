#!/usr/bin/env bash
# Test the two architecture rules by BREAKING them on purpose (#84).
#
# Both rules exist so that review does not have to enforce them. A rule nobody has
# ever seen fail is a comment with extra steps, so this adds the violation, runs
# the build, and requires it to fail — with a clean-tree baseline first, so a check
# that always fails cannot pass for the wrong reason.
#
# Runs in a container, because the point is that no local JDK is needed:
#
#   docker run --rm -v "$PWD/android:/host:ro" gradle:8.10-jdk21 /host/verify.sh
#   podman run --rm -v "$PWD/android:/host:ro" gradle:8.10-jdk21 /host/verify.sh
#
# Only the `:core:*` JVM modules are exercised. The Android modules need the SDK;
# CI installs it, and this script deliberately does not claim to cover them.
set -u

WORK=${WORK:-/w}
[ -d "$WORK" ] || { cp -r /host "$WORK"; }
cd "$WORK"
G="gradle --no-daemon -q"
fail=0

banner() { printf '\n=== %s\n' "$1"; }

banner "baseline: checkLayering passes on a clean tree"
$G checkLayering >/tmp/base.log 2>&1
if [ $? -eq 0 ]; then echo "  ok"; else
    echo "  *** the baseline already fails — every result below is meaningless"
    tail -5 /tmp/base.log; exit 1
fi

banner "rule 1: an android.* import in a :core: module must not compile"
VIOL=core/vocab/src/main/kotlin/com/yazses/core/vocab/_Violation.kt
mkdir -p "$(dirname "$VIOL")"
cat > "$VIOL" <<'KT'
package com.yazses.core.vocab
import android.content.Context
internal class Violation(val c: Context)
KT
$G :core:vocab:compileKotlin >/tmp/r1.log 2>&1
rc=$?
rm -f "$VIOL"
if [ $rc -ne 0 ]; then
    echo "  ENFORCED (exit $rc)"
    grep -m1 -i "unresolved reference 'android'" /tmp/r1.log || true
else
    echo "  *** NOT ENFORCED — it compiled"; fail=1
fi

banner "rule 2: a :core: -> :feature: dependency must fail the build"
cp core/vocab/build.gradle.kts /tmp/vocab.bak
printf '\ndependencies { implementation(project(":feature:ime")) }\n' >> core/vocab/build.gradle.kts
$G checkLayering >/tmp/r2.log 2>&1
rc=$?
cp /tmp/vocab.bak core/vocab/build.gradle.kts
if [ $rc -ne 0 ]; then
    echo "  ENFORCED (exit $rc)"
    grep -m2 "Forbidden module dependencies\|:core:vocab" /tmp/r2.log || true
else
    echo "  *** NOT ENFORCED — the dependency was accepted"; fail=1
fi

banner "the core modules still build and test"
$G :core:postprocess:test :core:commands:test :core:vocab:test >/tmp/t.log 2>&1
if [ $? -eq 0 ]; then echo "  ok"; else echo "  *** tests failed"; tail -10 /tmp/t.log; fail=1; fi

printf '\n'
[ $fail -eq 0 ] && echo "ALL RULES ENFORCED" || echo "SOME RULES ARE NOT ENFORCED"
exit $fail
