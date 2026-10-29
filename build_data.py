"""Clean the raw GHL records and build the dashboard page (site/index.html).

Every rule that removes or holds back a record is counted, so the dashboard can
show the owner exactly what was taken out and why.
"""
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
RAW = ROOT.parent / "data" / "raw"
SITE = ROOT / "site"

PIPELINE_NAME = "Sales Pipeline"
PROJECT_TAG = "dash-project"          # marks this agency's records in the shared sandbox
INTERNAL_TAGS = {"internal", "test", "staff"}
TEST_PATTERN = re.compile(r"\b(test|demo|dummy|fake|sample)\b", re.I)
UNKNOWN_SOURCE = "Unknown source"
OUTLIER_MULTIPLE = 5                  # a deal worth more than 5x the typical deal is held back

# How the 8 GHL stages map onto the journey a lead takes.
REACHED_BOOKING = {"Booked call", "Closed", "Cancelled", "No Show", "Follow Up", "Lost"}
CALL_HAPPENED = {"Closed", "Follow Up", "Lost"}
FUNNEL_STEPS = ["Leads", "Opted in", "Qualified", "Call booked", "Call happened", "Sale closed"]


def load(name):
    return json.loads((RAW / f"{name}.json").read_text(encoding="utf-8"))


def clean_source(value):
    value = re.sub(r"\s+", " ", (value or "")).strip()
    return value.title().replace("Linkedin", "LinkedIn") if value else UNKNOWN_SOURCE


def person_key(contact):
    name = re.sub(r"\s+", " ", (contact.get("contactName") or "")).strip().lower()
    company = re.sub(r"\s+", " ", (contact.get("companyName") or "")).strip().lower()
    return (name, company) if name else None


def email_key(contact):
    email = (contact.get("email") or "").strip().lower()
    if "@" not in email:
        return None
    local, domain = email.split("@", 1)
    local = re.sub(r"\.\d+$", "", local.split("+", 1)[0])  # jane.doe7.2@ and jane.doe7+x@ -> jane.doe7@
    return f"{local}@{domain}"


def find_duplicates(contacts, deal_by_contact):
    """Return ids of extra copies. The copy with a deal (else the oldest) is the one kept."""
    parent = {c["id"]: c["id"] for c in contacts}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for key_fn in (person_key, email_key):
        seen = {}
        for c in contacts:
            key = key_fn(c)
            if key is None:
                continue
            if key in seen:
                parent[root(c["id"])] = root(seen[key])
            else:
                seen[key] = c["id"]

    groups = defaultdict(list)
    for c in contacts:
        groups[root(c["id"])].append(c)

    extras = set()
    for members in groups.values():
        if len(members) > 1:
            members.sort(key=lambda c: (c["id"] not in deal_by_contact, c.get("dateAdded") or ""))
            extras.update(c["id"] for c in members[1:])
    return extras


def build():
    pipelines, deals_raw, contacts_raw = load("pipelines"), load("opportunities"), load("contacts")
    pipeline = next(p for p in pipelines if p["name"] == PIPELINE_NAME)
    stage_names = [s["name"] for s in sorted(pipeline["stages"], key=lambda s: s["position"])]
    stage_by_id = {s["id"]: s["name"] for s in pipeline["stages"]}

    # 1. Which records are this agency's?
    ours = [c for c in contacts_raw if PROJECT_TAG in (c.get("tags") or [])]
    if not ours:
        raise SystemExit(f'No contact carries the tag "{PROJECT_TAG}". If the agency\'s records are marked '
                         "differently in this location, change PROJECT_TAG at the top of build_data.py.")
    our_ids = {c["id"] for c in ours}
    deals = [d for d in deals_raw if d["contactId"] in our_ids]
    deal_by_contact = {d["contactId"]: d for d in deals}

    # 2. Internal / test leads
    def is_internal(c):
        tags = {t.lower() for t in (c.get("tags") or [])}
        text = f'{c.get("contactName") or ""} {c.get("companyName") or ""} {(c.get("email") or "").split("@")[0]}'
        return bool(tags & INTERNAL_TAGS) or bool(TEST_PATTERN.search(text))

    internal_ids = {c["id"] for c in ours if is_internal(c)}
    after_internal = [c for c in ours if c["id"] not in internal_ids]

    # 3. Duplicates
    duplicate_ids = find_duplicates(after_internal, deal_by_contact)
    leads = [c for c in after_internal if c["id"] not in duplicate_ids]
    lead_ids = {c["id"] for c in leads}
    deals = [d for d in deals if d["contactId"] in lead_ids]

    # 4. Suspicious deal values
    positive = [d["monetaryValue"] for d in deals if (d.get("monetaryValue") or 0) > 0]
    typical = statistics.median(positive)
    ceiling = typical * OUTLIER_MULTIPLE
    held_back = [d for d in deals if (d.get("monetaryValue") or 0) > ceiling]
    no_amount = [d for d in deals if not d.get("monetaryValue")]

    # 5. Per-source numbers
    rows = {}
    for c in leads:
        src = clean_source(c.get("source"))
        row = rows.setdefault(src, {
            "name": src, "leads": 0, "notInPipeline": 0, "stages": {s: 0 for s in stage_names},
            "revenue": 0, "heldBackDeals": 0, "heldBackValue": 0, "closedNoAmount": 0,
        })
        row["leads"] += 1
        deal = deal_by_contact.get(c["id"])
        if deal is None:
            row["notInPipeline"] += 1
            continue
        stage = stage_by_id[deal["pipelineStageId"]]
        row["stages"][stage] += 1
        if stage == "Closed":
            value = deal.get("monetaryValue") or 0
            if value > ceiling:
                row["heldBackDeals"] += 1
                row["heldBackValue"] += value
            elif value == 0:
                row["closedNoAmount"] += 1
            else:
                row["revenue"] += value

    for row in rows.values():
        st = row["stages"]
        in_pipeline = sum(st.values())
        # Consistency rule: the stage breakdown must add up to the reported lead count, or no page is built.
        assert in_pipeline + row["notInPipeline"] == row["leads"], row["name"]
        counted_sales = st["Closed"] - row["heldBackDeals"] - row["closedNoAmount"]
        row["inPipeline"] = in_pipeline
        row["funnel"] = [
            row["leads"],
            in_pipeline,
            in_pipeline - st["Disqualified"],
            sum(st[s] for s in REACHED_BOOKING),
            sum(st[s] for s in CALL_HAPPENED),
            st["Closed"],
        ]
        row["sales"] = st["Closed"]
        row["avgSale"] = round(row["revenue"] / counted_sales) if counted_sales else 0
        row["revenuePerLead"] = round(row["revenue"] / row["leads"]) if row["leads"] else 0

    sources = sorted(rows.values(), key=lambda r: -r["leads"])
    add_advice(sources)

    others = len(contacts_raw) - len(ours)
    other_deals = len(deals_raw) - len([d for d in deals_raw if d["contactId"] in our_ids])
    cleanup = {
        "contactsInSandbox": len(contacts_raw),
        "dealsInPipeline": len(deals_raw),
        "leadsCounted": len(leads),
        "dealsCounted": len(deals),
        "removed": [
            {"what": "Records from other people's projects", "count": others,
             "why": f"The system is shared. Only contacts tagged \"{PROJECT_TAG}\" are this agency's leads. "
                    f"{other_deals} deals attached to those other contacts were left out too: they sat in the "
                    "same pipeline but came from a separate demo batch, all dumped in Disqualified."},
            {"what": "Internal and test leads", "count": len(internal_ids),
             "why": "Tagged \"internal\": staff testing the website form, not real prospects. "
                    "Counting them would make the website look better at producing leads than it is."},
            {"what": "Duplicate contacts", "count": len(duplicate_ids),
             "why": "Same person at the same company entered twice. The copy had no deal and often a "
                    "different source, so it would have given credit to the wrong channel. The original was kept."},
        ],
        "heldBack": [
            {"what": "Sales with an unbelievable amount", "count": sum(r["heldBackDeals"] for r in sources),
             "value": sum(r["heldBackValue"] for r in sources),
             "why": f"A typical deal is about ${typical:,.0f}. These are recorded at more than "
                    f"{OUTLIER_MULTIPLE} times that, which looks like a typing mistake. The sale still counts "
                    "as a sale; its amount is left out of revenue until someone confirms it.",
             "items": [{"deal": d["name"].split(" - ")[0], "source": clean_source(d.get("source")),
                        "stage": stage_by_id[d["pipelineStageId"]], "value": d["monetaryValue"]}
                       for d in held_back]},
            {"what": "Sales with no amount entered", "count": sum(r["closedNoAmount"] for r in sources),
             "value": 0,
             "why": "Marked Closed but the amount is $0. Counted as a sale, adds nothing to revenue. "
                    "Fill in the amount in GoHighLevel and it will show up here.",
             "items": [{"deal": d["name"].split(" - ")[0], "source": clean_source(d.get("source")),
                        "stage": stage_by_id[d["pipelineStageId"]], "value": 0}
                       for d in no_amount if stage_by_id[d["pipelineStageId"]] == "Closed"]},
        ],
        "unknownSource": rows.get(UNKNOWN_SOURCE, {}).get("leads", 0),
        "typicalDeal": typical,
    }
    return {
        # When the records were downloaded, not when the page was built: an old download must not look fresh.
        "updatedAt": datetime.fromtimestamp((RAW / "opportunities.json").stat().st_mtime, timezone.utc)
                             .isoformat(timespec="seconds"),
        "stages": stage_names,
        "funnelSteps": FUNNEL_STEPS,
        "sources": sources,
        "cleanup": cleanup,
    }


def add_advice(sources):
    """Budget call per source. No ad spend exists, so the yardstick is revenue earned per lead."""
    mid = statistics.median(r["revenuePerLead"] for r in sources)
    for r in sources:
        leads, sales = r["leads"], r["sales"]
        rate = f"{sales} of {leads} leads became sales"
        if r["revenuePerLead"] >= mid * 1.25 and sales >= 2:
            r["verdict"] = "more"
            r["reason"] = f"{rate}, earning ${r['revenuePerLead']:,} per lead. Among the best."
        elif r["revenuePerLead"] <= mid * 0.6:
            r["verdict"] = "less"
            r["reason"] = (f"{rate}, earning ${r['revenuePerLead']:,} per lead. Among the weakest."
                           if sales else f"{leads} leads and no confirmed sale yet.")
        else:
            r["verdict"] = "same"
            r["reason"] = f"{rate}, earning ${r['revenuePerLead']:,} per lead. Middle of the pack."
        if r["heldBackDeals"]:
            if r["verdict"] == "less":  # don't cut a source on the strength of a number we set aside
                r["verdict"] = "same"
                r["reason"] = (f"{rate}, earning ${r['revenuePerLead']:,} per lead on confirmed amounts. "
                               "Looks weak, but hold steady until the amount below is confirmed.")
            r["reason"] += f" {r['heldBackDeals']} sale has an amount to confirm, which could change this."
    return sources


def main():
    data = build()
    SITE.mkdir(exist_ok=True)
    template = (ROOT / "dashboard_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (SITE / "index.html").write_text(template.replace("/*__DATA__*/null", payload), encoding="utf-8")
    (RAW.parent / "dashboard_data.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")

    c = data["cleanup"]
    print(f"leads counted: {c['leadsCounted']}  deals counted: {c['dealsCounted']}")
    for item in c["removed"]:
        print(f"  removed {item['count']:>3}  {item['what']}")
    for item in c["heldBack"]:
        print(f"  held    {item['count']:>3}  {item['what']}  (${item['value']:,})")
    print(f"{'source':<18}{'leads':>6}{'in pipe':>8}{'sales':>6}{'revenue':>10}{'$/lead':>8}  verdict   funnel")
    for r in data["sources"]:
        print(f"{r['name']:<18}{r['leads']:>6}{r['inPipeline']:>8}{r['sales']:>6}{r['revenue']:>10,}{r['revenuePerLead']:>8,}  {r['verdict']:<8}  {r['funnel']}")


if __name__ == "__main__":
    main()
