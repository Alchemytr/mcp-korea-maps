"""Travel-focused MCP extensions for the Korea Maps server.

Run this module instead of ``mcp_maps.server`` to expose all existing tools plus
travel-friendly nearby place search.
"""

from typing import Any

from mcp_maps.server import mcp, get_api_client, logger


@mcp.tool
async def search_nearby_places(
    keyword: str,
    longitude: float,
    latitude: float,
    radius: int = 2000,
    category_group_code: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find nearby Korean places, businesses or landmarks.

    Results are sorted by distance and condensed for travel use.

    Args:
        keyword: What to search for, in Korean or English where Kakao recognises it.
        longitude: Centre longitude (x coordinate).
        latitude: Centre latitude (y coordinate).
        radius: Search radius in metres, from 1 to 20,000. Defaults to 2 km.
        category_group_code: Optional Kakao category group code. Useful examples:
            FD6 food, CE7 cafe, CS2 convenience store, HP8 hospital,
            PM9 pharmacy, AT4 tourist attraction.
        limit: Number of results to return, from 1 to 15.

    Returns:
        A concise dictionary containing query metadata and nearby places, including
        name, category, phone, address, coordinates, distance and Kakao Map URL.
    """
    try:
        if not 1 <= radius <= 20000:
            raise ValueError("radius must be between 1 and 20000 metres")
        if not 1 <= limit <= 15:
            raise ValueError("limit must be between 1 and 15")

        client = get_api_client()
        raw = await client.search_by_keyword(
            keyword,
            longitude=longitude,
            latitude=latitude,
            radius=radius,
            category_group_code=category_group_code,
            sort="distance",
            size=limit,
        )

        places = []
        for doc in raw.get("documents", []):
            distance = doc.get("distance")
            places.append(
                {
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
            )

        return {
            "query": keyword,
            "centre": {"longitude": longitude, "latitude": latitude},
            "radius_metres": radius,
            "count": len(places),
            "places": places,
            "meta": raw.get("meta", {}),
        }
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
    # Preserve the same FastMCP CLI behaviour as the base server while exposing
    # the additional travel tool registered above.
    mcp.run()
