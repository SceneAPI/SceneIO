# Backend qualification receipts

This directory stores compact, reviewable receipts for binding backend
decisions. Full qualification reports retain every raw sample and can be
several megabytes; they are generated artifacts and remain outside the source
tree. Each checked receipt binds one full report by SHA-256 and records the
exact source, configuration, corpus, wheels, gate accounting, failed gates,
and decision-driving aggregates needed to audit the ledger.

Receipts do not replace the full report when reproducing a measurement. Run
the platform job defined in `.github/workflows/backend-qualification.yml`
from the receipt's source commit, then compare the new raw samples and gate
result under the frozen methodology. Timing, process, path, and RSS fields are
intentionally run-specific, so a reproduction is not expected to have the
original report's SHA-256. The recorded hash identifies the original report
from which the receipt was derived.
