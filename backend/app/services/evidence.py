from app.schemas.travel import EvidenceItem, Place

TRUSTED_SOURCE_TYPES = {
    "reddit",
    "google_maps",
    "official_open_data",
    "curated",
    "curated_must_go",
}


def build_evidence(stops: list[Place]) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    seen: set[tuple[str, str]] = set()

    for stop in stops:
        if stop.source_type not in TRUSTED_SOURCE_TYPES or not stop.source_url:
            continue

        key = (stop.name, stop.source_url)
        if key in seen:
            continue
        seen.add(key)

        if stop.source_type == "google_maps":
            support_summary = (
                "Google Maps supports the map reference for this stop and, when available, "
                "the displayed rating and opening-hours status."
            )
            source_title = stop.source_title or "Google Maps place details"
        elif stop.source_type == "official_open_data":
            support_summary = (
                "Official open-data records support this event or activity, including "
                "schedule, venue, price, and source page when provided."
            )
            source_title = stop.source_title or "Official Paris open-data record"
        elif stop.source_type in {"curated", "curated_must_go"}:
            support_summary = (
                "A curated TravelBuddy place record supports why this stop fits the request, "
                "and the attached Google Maps link is provided for navigation."
            )
            source_title = stop.source_title or "Curated TravelBuddy place reference"
        else:
            support_summary = (
                "Reddit community discussion is used as local-style evidence for why "
                "this stop fits the request."
            )
            source_title = stop.source_title or "Reddit community recommendation"

        evidence.append(
            EvidenceItem(
                place_name=stop.name,
                source_type=stop.source_type,
                source_title=source_title,
                source_url=stop.source_url,
                support_summary=support_summary,
            )
        )

    return evidence
