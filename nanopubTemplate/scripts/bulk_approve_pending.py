#!/usr/bin/env python3
"""
Bulk-approve (or reject) every nanopub currently shown as "pending" in the
mvikg/r/kg sample/variant/phenotype pending views.

For each pending record it builds a nanopub from the "Approving or
disapproving of a nanopublication" template (RAkhTlKa-i0miq_DN3V4HSv-btlDgwzg8qPUesrsJ0k9Q),
signs it with the local profile key, and -- only if --publish is given --
publishes it to the live network.

Usage:
    python3 scripts/bulk_approve_pending.py                 # dry run: list what would be approved
    python3 scripts/bulk_approve_pending.py --sign           # also sign (writes tmp/approvals/*.trig)
    python3 scripts/bulk_approve_pending.py --sign --publish # sign AND publish (asks for confirmation)
    python3 scripts/bulk_approve_pending.py --verdict disapprovesOf --sign --publish

Never publishes without --publish being passed explicitly, and always prints
the full list of nanopubs it is about to act on before doing anything
irreversible.
"""
import argparse
import csv
import io
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

JAR = "./nanopub-1.95.1-jar-with-dependencies.jar"
PROFILE = os.path.expanduser("~/.nanopub/profile.yaml")
OUT_DIR = "tmp/approvals"
RECORD_FILE = "publication-record.json"

TEMPLATE_ASSERTION = "https://w3id.org/np/RAkhTlKa-i0miq_DN3V4HSv-btlDgwzg8qPUesrsJ0k9Q/template"
TEMPLATE_PROVENANCE = "https://w3id.org/np/RA7lSq6MuK_TIC6JMSHvLtee3lpLoZDOqLJCLXevnrPoU"  # "Attributed to myself/others"
TEMPLATE_PUBINFO_CREATOR = "https://w3id.org/np/RA-N4_kFxcruvBTlo1yJv29E4SLOXsx5KO_th69PprMrA"
TEMPLATE_PUBINFO_LICENSE = "https://w3id.org/np/RACJ58Gvyn91LqCKIO9zu1eijDQIeEff28iyDrJgjSJF8"

# the three pending-record queries whose rows we act on (API artifact code / query name)
PENDING_QUERIES = [
    ("samples", "RAtfKIc1s4rkceik6pMD0HqT2bUvi8xetiypOjlbZ8LTw", "get-kg-pending-samples"),
    ("variants", "RAAby6NwDrtA83noSeFJlHIammY4k1HDzvfXI-Ekf3IO8", "get-kg-pending-variants"),
    ("phenotypes", "RAYjnWBjoRwfBZg17SjJAdn6Zq9skc8KNmxAw5Pcg3Wn4", "get-kg-pending-phenotypes"),
]

TRIG_TEMPLATE = """@prefix this: <http://purl.org/nanopub/temp/{tempid}/> .
@prefix sub: <http://purl.org/nanopub/temp/{tempid}/> .
@prefix np: <http://www.nanopub.org/nschema#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix nt: <https://w3id.org/np/o/ntemplate/> .
@prefix npx: <http://purl.org/nanopub/x/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix orcid: <https://orcid.org/> .
@prefix prov: <http://www.w3.org/ns/prov#> .

sub:Head {{
  this: a np:Nanopublication;
    np:hasAssertion sub:assertion;
    np:hasProvenance sub:provenance;
    np:hasPublicationInfo sub:pubinfo .
}}

sub:assertion {{
  orcid:{orcid} npx:{verdict} <{target}> .
}}

sub:provenance {{
  sub:assertion prov:wasAttributedTo orcid:{orcid} .
}}

sub:pubinfo {{
  this: dct:created "{timestamp}"^^xsd:dateTime;
    rdfs:label "{verdict_word} of {target_short}";
    dct:creator orcid:{orcid};
    dct:license <https://creativecommons.org/licenses/by/4.0/>;
    nt:wasCreatedFromProvenanceTemplate <{prov_tpl}>;
    nt:wasCreatedFromPubinfoTemplate <{pubinfo_tpl1}>, <{pubinfo_tpl2}>;
    nt:wasCreatedFromTemplate <{assertion_tpl}> .
}}
"""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_pending(code, name):
    url = f"https://query.knowledgepixels.com/api/{code}/{name}"
    req = urllib.request.Request(url, headers={"Accept": "text/csv"})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdict", choices=["approvesOf", "disapprovesOf"], default="approvesOf")
    ap.add_argument("--sign", action="store_true", help="write and sign a nanopub per pending record")
    ap.add_argument("--publish", action="store_true", help="publish the signed nanopubs to the live network")
    ap.add_argument("--orcid", default=None, help="override signer ORCID (default: read from profile)")
    ap.add_argument("--limit", type=int, default=None, help="only act on the first N pending records (for testing)")
    args = ap.parse_args()

    orcid = args.orcid
    if not orcid:
        with open(PROFILE) as f:
            for line in f:
                if line.strip().startswith("orcid_id"):
                    orcid = line.split(":", 1)[1].strip().rstrip("/").split("/")[-1]
                    break
    if not orcid:
        print("No ORCID found in profile and none given with --orcid.", file=sys.stderr)
        sys.exit(1)

    all_rows = []
    for category, code, qname in PENDING_QUERIES:
        rows = fetch_pending(code, qname)
        for r in rows:
            all_rows.append((category, r))

    if not all_rows:
        print("No pending records found. Nothing to do.")
        return

    if args.limit:
        all_rows = all_rows[:args.limit]

    print(f"Found {len(all_rows)} pending record(s) (after --limit):" if args.limit else f"Found {len(all_rows)} pending record(s):")
    for category, r in all_rows:
        name = r.get("Name_label") or r.get("Name") or "?"
        np_uri = r.get("np")
        print(f"  [{category}] {name}  ->  {np_uri}")

    if not args.sign:
        print("\n(dry run only -- pass --sign to build and sign the approval nanopubs)")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    signed_files = []
    for category, r in all_rows:
        target = r["np"]
        name = r.get("Name_label") or r.get("Name") or target
        tempid = "npappr" + target.rsplit("/", 1)[-1][:6]
        trig = TRIG_TEMPLATE.format(
            tempid=tempid,
            orcid=orcid,
            verdict=args.verdict,
            target=target,
            timestamp=now_iso(),
            verdict_word="Approval" if args.verdict == "approvesOf" else "Disapproval",
            target_short=name,
            prov_tpl=TEMPLATE_PROVENANCE,
            pubinfo_tpl1=TEMPLATE_PUBINFO_CREATOR,
            pubinfo_tpl2=TEMPLATE_PUBINFO_LICENSE,
            assertion_tpl=TEMPLATE_ASSERTION,
        )
        code = target.rsplit("/", 1)[-1]
        unsigned = os.path.join(OUT_DIR, f"{category}-{code}.trig")
        signed = os.path.join(OUT_DIR, f"{category}-{code}-signed.trig")
        with open(unsigned, "w") as f:
            f.write(trig)

        result = subprocess.run(
            ["java", "-jar", JAR, "sign", "-o", signed, unsigned],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"SIGN FAILED for {target}:\n{result.stderr}", file=sys.stderr)
            continue
        signed_files.append((category, target, signed))
        print(f"signed: {signed}")

    print(f"\n{len(signed_files)}/{len(all_rows)} signed successfully.")

    if not args.publish:
        print("(not publishing -- pass --publish to push these to the live network)")
        return

    print(f"\nAbout to PUBLISH {len(signed_files)} {args.verdict} nanopub(s) to the LIVE network, signed as {orcid}.")
    confirm = input("Type 'yes' to proceed: ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return

    record = {}
    if os.path.exists(RECORD_FILE):
        with open(RECORD_FILE) as f:
            record = json.load(f)

    for category, target, signed in signed_files:
        result = subprocess.run(
            ["java", "-jar", JAR, "publish", signed],
            capture_output=True, text=True,
        )
        ok = "nanopub published at" in result.stdout + result.stderr
        print(f"[{'OK' if ok else 'FAIL'}] {category} {target}")
        if ok:
            with open(signed) as f:
                text = f.read()
            import re
            new_uri = re.search(r"@prefix sub: <(https://w3id\.org/np/[A-Za-z0-9_-]+)/>", text).group(1)
            key = f"{args.verdict}-{category}-{target.rsplit('/', 1)[-1]}"
            record[key] = {
                "nanopub": new_uri,
                "registry": "live",
                "published": now_iso(),
                "supersedes": None,
                "file": signed,
                "signer": f"https://orcid.org/{orcid}",
                "note": f"{args.verdict} verdict on {target}",
            }

    with open(RECORD_FILE, "w") as f:
        json.dump(record, f, indent=2)
    print(f"\nUpdated {RECORD_FILE}.")


if __name__ == "__main__":
    main()
