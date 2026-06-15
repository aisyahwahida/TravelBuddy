from __future__ import annotations

"""
geo_cluster.py — Geographic clustering for route-aware day planning.

Groups candidate places into compact geographic neighbourhoods so each day
can be anchored to one area, preventing zig-zagging routes.

Public API
----------
  cluster_places(places, intent) → list[PlaceCluster]
  select_day_cluster(clusters, used_ids, day_index, intent) → DayClusterContext | None

DayClusterContext is passed into day_planner.calculate_slot_score() so that
in-cluster / near-center places receive a route-efficiency bonus.
"""

import logging
import math
from dataclasses import dataclass, field

from app.schemas.travel import Place, TravelIntent
from app.services.place_identity import place_identity_key

logger = logging.getLogger(__name__)

CLUSTER_RADIUS_KM = 1.5     # DBSCAN eps / greedy radius fallback
MIN_CLUSTER_SAMPLES = 2     # DBSCAN min_samples
FAR_FROM_CENTER_KM = 3.0   # distance at which the center penalty kicks in


# ─── Haversine (inlined — geo_cluster must not import day_planner) ────────────

def _hav(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class PlaceCluster:
    cluster_id: int
    center_lat: float
    center_lng: float
    candidate_count: int
    average_score: float
    slot_coverage_score: float   # 0–1: fraction of slot types represented
    compactness_score: float     # avg km from center (lower = tighter cluster)
    has_must_go: bool
    has_hidden_gem: bool
    has_food: bool
    places: list[Place] = field(default_factory=list)
    place_keys: set[str] = field(default_factory=set)


@dataclass
class DayClusterContext:
    cluster_id: int
    center_lat: float
    center_lng: float
    place_keys: set[str]   # identity keys of every place inside the cluster


# ─── Slot-type helpers (inlined to avoid circular import with day_planner) ────

def _is_food_geo(p: Place) -> bool:
    tags = {t.lower() for t in p.tags}
    h = f"{p.category} {p.name}".lower()
    is_cafe = bool({"cafe", "cafes", "coffee", "espresso"}.intersection(tags)) or any(
        t in h for t in ("cafe", "coffee", "espresso")
    )
    is_rest = "restaurant" in tags or "bistro" in tags or "restaurant" in h
    is_market = bool({"market", "markets", "marketplace"}.intersection(tags)) or any(
        t in h for t in ("market", "marketplace")
    )
    return is_cafe or is_rest or is_market


def _is_must_go_geo(p: Place) -> bool:
    tags = {t.lower() for t in p.tags}
    return (
        bool({"must_go", "landmark", "iconic", "famous"}.intersection(tags))
        or p.source_type == "curated_must_go"
    )


def _is_hidden_gem_geo(p: Place) -> bool:
    return p.tourist_trap_risk == "low" and not _is_must_go_geo(p) and not _is_food_geo(p)


def _is_museum_geo(p: Place) -> bool:
    tags = {t.lower() for t in p.tags}
    h = f"{p.category} {p.name}".lower()
    return bool(
        {"museum", "museums", "gallery", "art", "exhibition"}.intersection(tags)
    ) or any(t in h for t in ("museum", "musee", "gallery"))


def _is_park_geo(p: Place) -> bool:
    tags = {t.lower() for t in p.tags}
    h = f"{p.category} {p.name}".lower()
    return bool(
        {"park", "parks", "garden", "gardens", "walks", "viewpoint"}.intersection(tags)
    ) or any(t in h for t in ("park", "garden", "viewpoint", "promenade"))


def _slot_coverage(places: list[Place]) -> float:
    """Fraction of the 5 major slot types represented in this cluster (0–1)."""
    checks = [
        any(_is_must_go_geo(p) for p in places),
        any(_is_food_geo(p) for p in places),
        any(_is_hidden_gem_geo(p) for p in places),
        any(_is_museum_geo(p) for p in places),
        any(_is_park_geo(p) for p in places),
    ]
    return sum(checks) / len(checks)


def _place_quality(p: Place) -> float:
    """Rough quality proxy (0–1) used for cluster average_score."""
    rating = float(p.google_rating or 0)
    rating_s = min(1.0, max(0.0, (rating - 3.0) / 2.0)) if rating >= 3 else 0.0
    source_b = 0.2 if p.source_type in {"reddit", "curated_must_go"} else 0.0
    photo_b = 0.1 if (p.photo_name or p.wiki_thumb_url) else 0.0
    return min(1.0, 0.5 + 0.2 * rating_s + source_b + photo_b)


# ─── Clustering algorithms ────────────────────────────────────────────────────

def _dbscan_groups(places: list[Place]) -> list[list[Place]]:
    """DBSCAN clustering with haversine metric; falls back to radius grouping."""
    try:
        import numpy as np
        from sklearn.cluster import DBSCAN

        coords = np.radians([[p.latitude, p.longitude] for p in places])
        eps_rad = CLUSTER_RADIUS_KM / 6371.0
        labels = DBSCAN(
            eps=eps_rad, min_samples=MIN_CLUSTER_SAMPLES, metric="haversine"
        ).fit_predict(coords)

        groups: dict[int, list[Place]] = {}
        for label, place in zip(labels, places):
            groups.setdefault(int(label), []).append(place)

        # Noise points (label = -1): assign to nearest cluster or start a new one.
        noise = groups.pop(-1, [])
        result = list(groups.values())
        for place in noise:
            if not result:
                result.append([place])
                continue
            best_i, best_d = 0, float("inf")
            for i, g in enumerate(result):
                clat = sum(x.latitude for x in g) / len(g)
                clon = sum(x.longitude for x in g) / len(g)
                d = _hav(place.latitude, place.longitude, clat, clon)
                if d < best_d:
                    best_d, best_i = d, i
            if best_d < CLUSTER_RADIUS_KM * 2:
                result[best_i].append(place)
            else:
                result.append([place])

        return [g for g in result if g]

    except ImportError:
        logger.debug("sklearn not available — using radius clustering fallback")
        return _radius_groups(places)


def _radius_groups(places: list[Place]) -> list[list[Place]]:
    """Simple greedy radius clustering (sklearn fallback)."""
    groups: list[list[Place]] = []
    centers: list[tuple[float, float]] = []

    for place in places:
        best_i, best_d = -1, float("inf")
        for i, (clat, clon) in enumerate(centers):
            d = _hav(place.latitude, place.longitude, clat, clon)
            if d < CLUSTER_RADIUS_KM and d < best_d:
                best_d, best_i = d, i
        if best_i >= 0:
            groups[best_i].append(place)
            g = groups[best_i]
            centers[best_i] = (
                sum(p.latitude for p in g) / len(g),
                sum(p.longitude for p in g) / len(g),
            )
        else:
            groups.append([place])
            centers.append((place.latitude, place.longitude))

    return groups


# ─── Public API ───────────────────────────────────────────────────────────────

def cluster_places(places: list[Place], intent: TravelIntent) -> list[PlaceCluster]:
    """
    Cluster candidate places by geography and return scored PlaceCluster objects.
    Uses DBSCAN (sklearn) or radius-based fallback.
    """
    if not places:
        return []

    groups = _dbscan_groups(places)

    clusters: list[PlaceCluster] = []
    for cid, group in enumerate(groups):
        clat = sum(p.latitude for p in group) / len(group)
        clon = sum(p.longitude for p in group) / len(group)
        compact = sum(_hav(p.latitude, p.longitude, clat, clon) for p in group) / len(group)

        clusters.append(PlaceCluster(
            cluster_id=cid,
            center_lat=clat,
            center_lng=clon,
            candidate_count=len(group),
            average_score=sum(_place_quality(p) for p in group) / len(group),
            slot_coverage_score=_slot_coverage(group),
            compactness_score=compact,
            has_must_go=any(_is_must_go_geo(p) for p in group),
            has_hidden_gem=any(_is_hidden_gem_geo(p) for p in group),
            has_food=any(_is_food_geo(p) for p in group),
            places=list(group),
            place_keys={place_identity_key(p) for p in group},
        ))

    logger.debug(
        "geo_cluster: %d places → %d clusters | sizes=%s",
        len(places), len(clusters),
        [c.candidate_count for c in clusters],
    )

    return clusters


def _cluster_day_score(
    cluster: PlaceCluster,
    used_ids: set[int],
    day_index: int,
    intent: TravelIntent,
) -> float:
    """Multi-factor score for picking a cluster for a given day (higher = better)."""
    user_type = getattr(intent, "user_type", "") or "general"
    richness = min(1.0, cluster.candidate_count / 10.0)
    compactness = max(0.0, 1.0 - cluster.compactness_score / CLUSTER_RADIUS_KM)
    must_go_w = 0.15 if (user_type == "first_time_visitor" or day_index == 0) else 0.05
    gem_w = 0.15 if user_type in {"returning_visitor", "local_resident"} else 0.05

    score = (
        0.30 * richness
        + 0.25 * cluster.slot_coverage_score
        + 0.15 * compactness
        + (must_go_w if cluster.has_must_go else 0.0)
        + (gem_w if cluster.has_hidden_gem else 0.0)
        + (0.05 if cluster.has_food else 0.0)
    )
    if cluster.cluster_id in used_ids:
        score -= 0.40  # strong preference for an unvisited area
    return score


def select_day_cluster(
    clusters: list[PlaceCluster],
    used_ids: set[int],
    day_index: int,
    intent: TravelIntent,
) -> DayClusterContext | None:
    """
    Pick the best geographic cluster for a given day.
    Penalises already-used cluster IDs to spread days across the city.
    Returns None only when clusters is empty.
    """
    if not clusters:
        return None

    best = max(
        clusters,
        key=lambda c: _cluster_day_score(c, used_ids, day_index, intent),
    )

    logger.debug(
        "Day %d → cluster %d center=(%.4f,%.4f) count=%d cov=%.2f compact=%.2fkm",
        day_index + 1, best.cluster_id,
        best.center_lat, best.center_lng,
        best.candidate_count, best.slot_coverage_score,
        best.compactness_score,
    )

    return DayClusterContext(
        cluster_id=best.cluster_id,
        center_lat=best.center_lat,
        center_lng=best.center_lng,
        place_keys=best.place_keys,
    )
