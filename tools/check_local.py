"""
Run PF Sahi Hai over a folder of real documents, locally, and print structure only.

Nothing is written to disk, nothing leaves the machine, and no name, amount,
date, identifier or filename is ever printed. The password is read with
getpass, so it is not echoed and does not enter shell history.

    python tools/check_local.py "D:\path\to\folder"
"""

from __future__ import annotations

import getpass
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.ingest import sort_uploads          # noqa: E402
import app.engine as E                        # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    folder = pathlib.Path(sys.argv[1])
    if not folder.is_dir():
        print(f"not a folder: {folder}")
        return 2

    files = [f for f in sorted(folder.iterdir()) if f.is_file()]
    print(f"{len(files)} files")
    pwd = getpass.getpass("PDF/ZIP password (DDMMYYYY, blank to skip): ") or None

    items = [(f.name, f.read_bytes()) for f in files]
    r = sort_uploads(items, pwd)
    found = r["found"]

    print("\nrecognised")
    print(f"  Form 26AS       {'yes' if found['26as'] else 'no'}")
    print(f"  PF passbooks    {len(found['passbook'])}")
    print(f"  service history {'yes' if found['service_history'] else 'no'}")
    print(f"  bank statement  {'yes' if found['bank'] else 'no'}")

    refused = [x for x in r["report"] if not x["ok"]]
    if refused:
        print(f"\n{len(refused)} not used:")
        for x in refused:
            print(f"  - {x['message']}")

    if r["missing"]:
        print(f"\nblocked: needs {', '.join(r['missing'])}")
        return 1

    names = E.extract_names({"26as": found["26as"] or "",
                             "passbook": found["passbook"],
                             "bank": found["bank"] or ""})
    a = E.analyse(text_26as=found["26as"] or "", passbooks=found["passbook"],
                  service_history=found["service_history"] or "",
                  bank=found["bank"] or "", names=names)

    # Two axes, reported separately. Dates need EPFO's service history;
    # contributions need only the passbook and Form 26AS, which is what most
    # members can actually get hold of.
    pf = {o for c in a.result["contradictions"] for o in [c["employer"]]}
    gaps = [c for c in a.result["contradictions"] if c["kind"] == "CONTRIBUTION_GAP"]

    print("\nwhat could be checked")
    print(f"  dates                {a.dates_checked}")
    print(f"  contributions        {a.contributions_checked}")
    print(f"  gap findings         {len(gaps)}")
    for c in gaps:
        # Counts only. No employer name, no month, no amount.
        n = c["detail"].split(" month")[0].strip()
        print(f"    - one employer, {n} month(s) with tax deducted and no PF")

    print("\nresult")
    print(f"  record was checked   {a.checked}")
    print(f"  accounts             {len(a.accounts)}")
    print(f"  months contributed   {sum(x.months for x in a.accounts)}")
    print(f"  a balance was read   {a.total_balance > 0}")
    print(f"  a pension was read   {a.total_pension > 0}")
    print(f"  employers in 26AS    {len(a.deductors)}")
    print(f"  findings             {[c['kind'] for c in a.result['contradictions']]}")
    print(f"  other account refs   {len(a.related_ids)}")
    for line in a.reduced:
        print(f"  limited: {line}")
    print("\nNo document content was printed. Nothing was written to disk.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
