"""
Review queue for researcher submissions awaiting approval before nanopub
publication (see ../NANOPUB_INGESTION_PLAN.md). A flat TSV, one row per
submission -- same style as the existing <stem>_gene_map.tsv files, no new
database/dependency.

Every validated submission lands in 'pending_review' regardless of
flag_count (including flag_count == 0) -- flag_count is informational for
the reviewer's triage, not an auto-approve signal.

Usage:
    pipenv run python3 -m scripts.review_queue list
    pipenv run python3 -m scripts.review_queue approve sub001 --reviewer dtandon
    pipenv run python3 -m scripts.review_queue reject sub001 --reviewer dtandon --notes "taxon ID mismatch, resubmit"
"""
import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = REPO_ROOT / "data" / "processed" / "review_queue.tsv"

FIELDNAMES = [
    "submission_id", "status", "flag_count", "reviewer",
    "decision_notes", "submitted_at", "reviewed_at",
]


def _read_all(queue_path: Path = QUEUE_PATH) -> list[dict]:
    if not queue_path.exists():
        return []
    with open(queue_path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _write_all(rows: list[dict], queue_path: Path = QUEUE_PATH) -> None:
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with open(queue_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def register_submission(submission_id: str, flag_count: int, queue_path: Path = QUEUE_PATH) -> None:
    """
    Add (or re-add) a submission to the queue at status 'pending_review'.
    Called from render_submission_rdf.py once validation/SO-resolution has
    run, so flag_count reflects the real ECO:0000035 count from that pass.
    Re-registering an existing submission_id overwrites its row (e.g. a
    resubmission after a rejection) rather than appending a duplicate.
    """
    rows = [r for r in _read_all(queue_path) if r["submission_id"] != submission_id]
    rows.append({
        "submission_id": submission_id,
        "status": "pending_review",
        "flag_count": str(flag_count),
        "reviewer": "",
        "decision_notes": "",
        "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reviewed_at": "",
    })
    _write_all(rows, queue_path)


def _set_decision(submission_id: str, status: str, reviewer: str, notes: str,
                   queue_path: Path = QUEUE_PATH) -> None:
    rows = _read_all(queue_path)
    for r in rows:
        if r["submission_id"] == submission_id:
            r["status"] = status
            r["reviewer"] = reviewer
            r["decision_notes"] = notes
            r["reviewed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _write_all(rows, queue_path)
            return
    raise ValueError(f"No queue entry for submission_id '{submission_id}'")


def approve(submission_id: str, reviewer: str, notes: str = "", queue_path: Path = QUEUE_PATH) -> None:
    _set_decision(submission_id, "approved", reviewer, notes, queue_path)


def reject(submission_id: str, reviewer: str, notes: str = "", queue_path: Path = QUEUE_PATH) -> None:
    _set_decision(submission_id, "rejected", reviewer, notes, queue_path)


def list_pending(queue_path: Path = QUEUE_PATH) -> list[dict]:
    return [r for r in _read_all(queue_path) if r["status"] == "pending_review"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List submissions currently pending review")

    p_approve = sub.add_parser("approve", help="Approve a submission")
    p_approve.add_argument("submission_id")
    p_approve.add_argument("--reviewer", required=True)
    p_approve.add_argument("--notes", default="")

    p_reject = sub.add_parser("reject", help="Reject a submission")
    p_reject.add_argument("submission_id")
    p_reject.add_argument("--reviewer", required=True)
    p_reject.add_argument("--notes", default="")

    args = parser.parse_args()

    if args.command == "list":
        pending = list_pending()
        if not pending:
            print("No submissions pending review.")
        for r in pending:
            print(f"{r['submission_id']}\tflags={r['flag_count']}\tsubmitted={r['submitted_at']}")
    elif args.command == "approve":
        approve(args.submission_id, args.reviewer, args.notes)
        print(f"Approved {args.submission_id}")
    elif args.command == "reject":
        reject(args.submission_id, args.reviewer, args.notes)
        print(f"Rejected {args.submission_id}")


if __name__ == "__main__":
    main()
