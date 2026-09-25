import pytest
from unittest.mock import AsyncMock

from mcp_maps.apis.kakao import KakaoApiClientError, KakaoMapsApiClient


@pytest.mark.asyncio
async def test_location_aware_keyword_search_builds_kakao_params():
    client = KakaoMapsApiClient(api_key="test-key")
    client._make_request = AsyncMock(return_value={"documents": [], "meta": {}})

    await client.search_by_keyword(
        "pharmacy",
        longitude=126.9780,
        latitude=37.5665,
        radius=1500,
        category_group_code="PM9",
        sort="distance",
        page=1,
        size=10,
    )

    client._make_request.assert_awaited_once_with(
        method="GET",
        base_url=client.KAKAO_LOCAL_API_BASE_URL,
        endpoint=client.KEYWORD_SEARCH_ENDPOINT,
        params={
            "query": "pharmacy",
            "x": 126.9780,
            "y": 37.5665,
            "radius": 1500,
            "category_group_code": "PM9",
            "sort": "distance",
            "page": 1,
            "size": 10,
        },
    )


@pytest.mark.asyncio
async def test_radius_requires_coordinates():
    client = KakaoMapsApiClient(api_key="test-key")

    with pytest.raises(KakaoApiClientError, match="radius requires longitude and latitude"):
        await client.search_by_keyword("cafe", radius=1000)


@pytest.mark.asyncio
async def test_distance_sort_requires_coordinates():
    client = KakaoMapsApiClient(api_key="test-key")

    with pytest.raises(KakaoApiClientError, match="distance sorting requires"):
        await client.search_by_keyword("cafe", sort="distance")


@pytest.mark.asyncio
@pytest.mark.parametrize("radius", [0, 20001])
async def test_radius_bounds(radius):
    client = KakaoMapsApiClient(api_key="test-key")

    with pytest.raises(KakaoApiClientError, match="radius must be between"):
        await client.search_by_keyword(
            "cafe", longitude=126.9780, latitude=37.5665, radius=radius
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 16])
async def test_size_bounds(size):
    client = KakaoMapsApiClient(api_key="test-key")

    with pytest.raises(KakaoApiClientError, match="size must be between"):
        await client.search_by_keyword("cafe", size=size)
