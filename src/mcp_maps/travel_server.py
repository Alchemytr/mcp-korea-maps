"""Travel-focused extensions for the Korea Maps MCP server.

Run this module instead of ``mcp_maps.server`` to expose all existing upstream
MCP tools plus a compact nearby-place search intended for travellers.
"""

from typing import Any

from mcp_maps.server import get_api_client, logger, mcp


KAKAO_CATEGORY_GROUPS = {
    "MT1": "large mart",
    "CS2": "convenience store",
    "PS3": "kindergarten",
    "SC4": "school",
    "AC5": "academy",
    "PK6": "parking",
    "OL7": "petrol station",
    "SW8": "subway station",
    "BK9": "bank",
    "CT1": "cultural facility",
    "AG2": "real estate agency",
    "PO3": "public institution",
    "AT4": "tourist attraction",
    "AD5": "accommodation",
    "FD6": "food",
    "CE7": "cafe",
    "HP8": "hospital",
    "PM9": "pharmacy",
}


def _condense_place(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert a Kakao Local API place record into a compact travel result."""
    distance = doc.get("distance")
    return {
        "id": doc.get("id"),
        "name": doc.get("place_name"),
        "category": doc.get("category_name"),
        "category_group": doc.get("category_group_name"),
        "phone": doc.get("phone"),
        "address": doc.get("road_address_name") or doc.get("address_name"),
        "longitude": float(doc["x"]) if doc.get("x") else None,
        "latitude": float(doc["y"]) if doc.get("y") else None,
        "distance_metres": int(distance) if distance else None,
        "kakao_map_url": doc.get("place_url"),
    }


async def _search_nearby_places(
    keyword: str,
    longitude: float,
    latitude: float,
    radius: int = 2000,
    category_group_code: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Implementation behind the MCP tool, separated for straightforward testing."""
    if not keyword.strip():
        raise ValueError("keyword must not be empty")
    if not 1 <= radius <= 20000:
        raise ValueError("radius must be between 1 and 20000 metres")
    if not 1 <= limit <= 15:
        raise ValueError("limit must be between 1 and 15")
    if category_group_code is not None and category_group_code not in KAKAO_CATEGORY_GROUPS:
        valid = ", ".join(sorted(KAKAO_CATEGORY_GROUPS))
        raise ValueError(f"unknown category_group_code; expected one of: {valid}")

    client = get_api_client()
    params: dict[str, Any] = {
        "query": keyword,
        "x": longitude,
        "y": latitude,
        "radius": radius,
        "sort": "distance",
        "size": limit,
    }
    if category_group_code:
        params["category_group_code"] = category_group_code

    raw = await client._make_request(
        method="GET",
        base_url=client.KAKAO_LOCAL_API_BASE_URL,
        endpoint=client.KEYWORD_SEARCH_ENDPOINT,
        params=params,
    )

    places = [_condense_place(doc) for doc in raw.get("documents", [])]
    return {
        "query": keyword,
        "centre": {"longitude": longitude, "latitude": latitude},
        "radius_metres": radius,
        "category_group_code": category_group_code,
        "count": len(places),
        "places": places,
        "meta": raw.get("meta", {}),
    }


@mcp.tool
async def search_nearby_places(
    keyword: str,
    longitude: float,
    latitude: float,
    radius: int = 2000,
    category_group_code: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find nearby Korean places, businesses or landmarks around a coordinate.

    Results are sorted by distance and returned in a compact format suited to
    travel planning and in-trip use.

    Args:
        keyword: Search term. Korean generally gives the strongest Kakao results,
            but common English place/business names may also work.
        longitude: Search-centre longitude (Kakao x coordinate).
        latitude: Search-centre latitude (Kakao y coordinate).
        radius: Search radius in metres, 1-20,000. Defaults to 2,000 m.
        category_group_code: Optional Kakao category group code, for example
            FD6 food, CE7 cafe, CS2 convenience store, HP8 hospital,
            PM9 pharmacy, AT4 tourist attraction, AD5 accommodation,
            SW8 subway station or OL7 petrol station.
        limit: Results to return, 1-15. Defaults to 10.
    """
    try:
        return await _search_nearby_places(
            keyword=keyword,
            longitude=longitude,
            latitude=latitude,
            radius=radius,
            category_group_code=category_group_code,
            limit=limit,
        )
    except Exception as exc:
        logger.error("Error in search_nearby_places: %s", exc)
        return {
            "error": str(exc),
            "keyword": keyword,
            "longitude": longitude,
            "latitude": latitude,
            "radius": radius,
        }


if __name__ == "__main__":
    mcp.run()
