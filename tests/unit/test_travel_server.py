import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_maps.travel_server import _search_nearby_places


@pytest.mark.asyncio
async def test_search_nearby_places_builds_location_query_and_condenses_results():
    client = MagicMock()
    client.KAKAO_LOCAL_API_BASE_URL = "https://dapi.kakao.com/v2/local"
    client.KEYWORD_SEARCH_ENDPOINT = "/search/keyword"
    client._make_request = AsyncMock(
        return_value={
            "documents": [
                {
                    "id": "123",
                    "place_name": "Test Pharmacy",
                    "category_name": "의료 > 약국",
                    "category_group_name": "약국",
                    "phone": "02-123-4567",
                    "address_name": "서울특별시 중구 테스트동 1",
                    "road_address_name": "서울특별시 중구 테스트로 1",
                    "x": "126.9780",
                    "y": "37.5665",
                    "distance": "325",
                    "place_url": "https://place.map.kakao.com/123",
                }
            ],
            "meta": {"total_count": 1, "is_end": True},
        }
    )

    with patch("mcp_maps.travel_server.get_api_client", return_value=client):
        result = await _search_nearby_places(
            keyword="pharmacy",
            longitude=126.9779,
            latitude=37.5663,
            radius=1500,
            category_group_code="PM9",
            limit=10,
        )

    client._make_request.assert_awaited_once_with(
        method="GET",
        base_url="https://dapi.kakao.com/v2/local",
        endpoint="/search/keyword",
        params={
            "query": "pharmacy",
            "x": 126.9779,
            "y": 37.5663,
            "radius": 1500,
            "sort": "distance",
            "size": 10,
            "category_group_code": "PM9",
        },
    )
    assert result["count"] == 1
    assert result["places"][0]["name"] == "Test Pharmacy"
    assert result["places"][0]["distance_metres"] == 325
    assert result["places"][0]["longitude"] == 126.9780


@pytest.mark.asyncio
@pytest.mark.parametrize("radius", [0, 20001])
async def test_search_nearby_places_validates_radius(radius):
    with pytest.raises(ValueError, match="radius must be between"):
        await _search_nearby_places("cafe", 126.9780, 37.5665, radius=radius)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 16])
async def test_search_nearby_places_validates_limit(limit):
    with pytest.raises(ValueError, match="limit must be between"):
        await _search_nearby_places("cafe", 126.9780, 37.5665, limit=limit)


@pytest.mark.asyncio
async def test_search_nearby_places_validates_category_group():
    with pytest.raises(ValueError, match="unknown category_group_code"):
        await _search_nearby_places(
            "anything", 126.9780, 37.5665, category_group_code="ZZ9"
        )
