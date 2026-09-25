import os
import httpx
import logging
import asyncio
import json
from typing import Dict, Optional, Any, List, Union, ClassVar, Literal, cast
from cachetools import TTLCache
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from ratelimit import limits, sleep_and_retry


class KakaoApiError(Exception):
    """Base exception for Kakao API errors"""

    def __init__(
        self,
        message: str,
        response: Optional[httpx.Response] = None,
        request: Optional[httpx.Request] = None,
    ):
        super().__init__(message)
        self.message = message
        self.response = response
        self.request = request

    def __str__(self) -> str:
        base_str = super().__str__()
        if self.response:
            base_str += f" (Status Code: {self.response.status_code})"
        if self.request:
            base_str += f" (Request URL: {self.request.url})"
        return base_str


class KakaoApiConnectionError(KakaoApiError):
    """Connection error with Kakao API"""

    def __init__(self, message: str, request: Optional[httpx.Request] = None):
        super().__init__(message, response=None, request=request)


class KakaoApiClientError(KakaoApiError):
    """Client-side error with Kakao API requests (4xx)"""

    pass


class KakaoApiServerError(KakaoApiError):
    """Server-side error with Kakao API operations (5xx)"""

    pass


class KakaoMapsApiClient:
    """
    Client for Kakao Maps and Kakao Mobility APIs with caching and rate limiting.

    Features:
    - Geocoding (address to coordinates)
    - Address search by place name
    - Location-aware keyword/place search
    - Direction search by address or coordinates
    - Future direction search with departure time
    - Multi-destination route optimization
    - Response caching with TTL
    - Rate limiting to respect API quotas
    - Automatic retries for transient errors
    - Connection pooling
    """

    KAKAO_LOCAL_API_BASE_URL = "https://dapi.kakao.com/v2/local"
    KAKAO_MOBILITY_API_BASE_URL = "https://apis-navi.kakaomobility.com/v1"

    GEOCODE_ENDPOINT = "/search/address"
    KEYWORD_SEARCH_ENDPOINT = "/search/keyword"
    DIRECTIONS_ENDPOINT = "/directions"
    FUTURE_DIRECTIONS_ENDPOINT = "/future/directions"
    MULTI_DESTINATION_DIRECTIONS_ENDPOINT = "/destinations/directions"

    _shared_client: ClassVar[Optional[httpx.AsyncClient]] = None
    _client_lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(
        self,
        api_key: str,
        cache_ttl: int = 3600,
        rate_limit_calls: int = 10,
        rate_limit_period: int = 1,
        concurrency_limit: int = 5,
    ):
        self.api_key = api_key
        if not self.api_key or self.api_key == "missing_api_key":
            raise ValueError("Kakao API key is required")

        self._logger_name = "kakao_maps_api_client"
        self._cache_ttl = cache_ttl
        self._rate_limit_calls = rate_limit_calls
        self._rate_limit_period = rate_limit_period
        self._concurrency_limit = concurrency_limit
        self._is_fully_initialized = False
        self._cache: Optional[TTLCache] = None
        self._request_semaphore: Optional[asyncio.Semaphore] = None
        self.logger: Optional[logging.Logger] = None

    def _ensure_full_initialization(self):
        if self._is_fully_initialized:
            return

        self.logger = logging.getLogger(self._logger_name)
        if not self.logger.hasHandlers():
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

        if not self.api_key or self.api_key == "missing_api_key":
            raise ValueError("Kakao API key is required")

        self._cache = TTLCache(maxsize=1000, ttl=self._cache_ttl)
        self._request_semaphore = asyncio.Semaphore(self._concurrency_limit)
        self._is_fully_initialized = True

    @property
    def cache(self) -> TTLCache:
        self._ensure_full_initialization()
        if self._cache is None:
            raise RuntimeError("Cache not initialized")
        return self._cache

    @classmethod
    async def get_shared_client(cls) -> httpx.AsyncClient:
        async with cls._client_lock:
            if cls._shared_client is None or cls._shared_client.is_closed:
                cls._shared_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0),
                    limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
                )
        return cls._shared_client

    @classmethod
    async def close_all_connections(cls):
        async with cls._client_lock:
            if cls._shared_client is not None and not cls._shared_client.is_closed:
                await cls._shared_client.aclose()
                cls._shared_client = None

    def _process_response_error(self, response: httpx.Response):
        if response.status_code >= 400:
            try:
                error_data = response.json()
                error_message = error_data.get("errorMessage", "Unknown error")
                if self.logger is not None:
                    self.logger.error(f"API Error Response: {error_data}")
            except (json.JSONDecodeError, ValueError):
                error_message = f"HTTP {response.status_code}: {response.text}"

            if 400 <= response.status_code < 500:
                raise KakaoApiClientError(error_message, response=response)
            elif 500 <= response.status_code < 600:
                raise KakaoApiServerError(error_message, response=response)
            else:
                raise KakaoApiError(error_message, response=response)

    def _get_cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        sorted_params = sorted(params.items())
        param_str = "&".join([f"{k}={v}" for k, v in sorted_params])
        return f"{endpoint}?{param_str}"

    @sleep_and_retry
    @limits(calls=10, period=1)
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(
            (httpx.ConnectTimeout, httpx.ConnectError, KakaoApiServerError)
        ),
        reraise=True,
    )
    async def _make_request(
        self,
        method: str,
        base_url: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        self._ensure_full_initialization()
        if self.logger is None or self._request_semaphore is None:
            raise RuntimeError("Client not properly initialized")

        cache_key = None
        if use_cache and method.upper() == "GET":
            cache_key = self._get_cache_key(endpoint, params or {})
            cached_response = self.cache.get(cache_key)
            if cached_response is not None:
                self.logger.debug(f"Cache hit for {cache_key}")
                return cached_response

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"KakaoAK {self.api_key}",
        }
        url = f"{base_url}{endpoint}"

        async with self._request_semaphore:
            try:
                client = await self.get_shared_client()
                if method.upper() == "GET":
                    response = await client.get(url, params=params, headers=headers)
                elif method.upper() == "POST":
                    response = await client.post(url, json=json_data, headers=headers)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                self._process_response_error(response)
                result = response.json()

                if use_cache and method.upper() == "GET" and cache_key:
                    self.cache[cache_key] = result
                    self.logger.debug(f"Cached response for {cache_key}")

                return result
            except httpx.ConnectError as e:
                self.logger.error(f"Connection error: {e}")
                raise KakaoApiConnectionError(f"Failed to connect to Kakao API: {e}")
            except httpx.TimeoutException as e:
                self.logger.error(f"Request timeout: {e}")
                raise KakaoApiConnectionError(f"Request to Kakao API timed out: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")
                raise

    async def geocode(self, place_name: str) -> Dict[str, Any]:
        params = {"query": place_name}
        return cast(
            Dict[str, Any],
            await self._make_request(
                method="GET",
                base_url=self.KAKAO_LOCAL_API_BASE_URL,
                endpoint=self.GEOCODE_ENDPOINT,
                params=params,
            ),
        )

    async def search_by_keyword(
        self,
        keyword: str,
        longitude: Optional[float] = None,
        latitude: Optional[float] = None,
        radius: Optional[int] = None,
        category_group_code: Optional[str] = None,
        sort: Optional[Literal["accuracy", "distance"]] = None,
        page: Optional[int] = None,
        size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Search places by keyword with optional location-aware filtering."""
        if (longitude is None) != (latitude is None):
            raise KakaoApiClientError("longitude and latitude must be provided together")
        if radius is not None:
            if longitude is None or latitude is None:
                raise KakaoApiClientError("radius requires longitude and latitude")
            if not 0 < radius <= 20000:
                raise KakaoApiClientError("radius must be between 1 and 20000 metres")
        if sort == "distance" and (longitude is None or latitude is None):
            raise KakaoApiClientError("distance sorting requires longitude and latitude")
        if page is not None and not 1 <= page <= 45:
            raise KakaoApiClientError("page must be between 1 and 45")
        if size is not None and not 1 <= size <= 15:
            raise KakaoApiClientError("size must be between 1 and 15")

        params: Dict[str, Any] = {"query": keyword}
        if longitude is not None and latitude is not None:
            params["x"] = longitude
            params["y"] = latitude
        if radius is not None:
            params["radius"] = radius
        if category_group_code:
            params["category_group_code"] = category_group_code
        if sort:
            params["sort"] = sort
        if page is not None:
            params["page"] = page
        if size is not None:
            params["size"] = size

        return cast(
            Dict[str, Any],
            await self._make_request(
                method="GET",
                base_url=self.KAKAO_LOCAL_API_BASE_URL,
                endpoint=self.KEYWORD_SEARCH_ENDPOINT,
                params=params,
            ),
        )

    async def direction_search_by_coordinates(
        self,
        origin_longitude: float,
        origin_latitude: float,
        dest_longitude: float,
        dest_latitude: float,
    ) -> Dict[str, Any]:
        params = {
            "origin": f"{origin_longitude},{origin_latitude}",
            "destination": f"{dest_longitude},{dest_latitude}",
        }
        return cast(
            Dict[str, Any],
            await self._make_request(
                method="GET",
                base_url=self.KAKAO_MOBILITY_API_BASE_URL,
                endpoint=self.DIRECTIONS_ENDPOINT,
                params=params,
            ),
        )

    async def direction_search_by_address(
        self, origin_address: str, dest_address: str
    ) -> Dict[str, Any]:
        async def get_coordinates_for_address(address: str) -> tuple:
            geocode_result = await self.geocode(address)
            if (
                geocode_result.get("documents")
                and geocode_result["documents"][0].get("x")
                and geocode_result["documents"][0].get("y")
            ):
                doc = geocode_result["documents"][0]
                return float(doc["x"]), float(doc["y"])

            keyword_result = await self.search_by_keyword(address)
            if (
                keyword_result.get("documents")
                and keyword_result["documents"][0].get("x")
                and keyword_result["documents"][0].get("y")
            ):
                doc = keyword_result["documents"][0]
                return float(doc["x"]), float(doc["y"])

            raise KakaoApiClientError(
                f"Could not find coordinates for address: {address}"
            )

        try:
            origin_coords, dest_coords = await asyncio.gather(
                get_coordinates_for_address(origin_address),
                get_coordinates_for_address(dest_address),
            )
        except Exception as e:
            raise KakaoApiClientError(
                f"Failed to get coordinates for one or both locations: {str(e)}"
            )

        origin_longitude, origin_latitude = origin_coords
        dest_longitude, dest_latitude = dest_coords
        return await self.direction_search_by_coordinates(
            origin_longitude, origin_latitude, dest_longitude, dest_latitude
        )

    async def future_direction_search_by_coordinates(
        self,
        origin_longitude: float,
        origin_latitude: float,
        destination_longitude: float,
        destination_latitude: float,
        departure_time: str,
        waypoints: Optional[str] = None,
        priority: Optional[Literal["RECOMMEND", "TIME", "DISTANCE"]] = None,
        avoid: Optional[str] = None,
        road_event: Optional[int] = None,
        alternatives: Optional[bool] = None,
        road_details: Optional[bool] = None,
        car_type: Optional[int] = None,
        car_fuel: Optional[Literal["GASOLINE", "DIESEL", "LPG"]] = None,
        car_hipass: Optional[bool] = None,
        summary: Optional[bool] = None,
    ) -> Dict[str, Any]:
        params = {
            "origin": f"{origin_longitude},{origin_latitude}",
            "destination": f"{destination_longitude},{destination_latitude}",
            "departure_time": departure_time,
        }
        if waypoints is not None:
            params["waypoints"] = waypoints
        if priority is not None:
            params["priority"] = priority
        if avoid is not None:
            params["avoid"] = avoid
        if road_event is not None:
            params["roadevent"] = str(road_event)
        if alternatives is not None:
            params["alternatives"] = str(alternatives).lower()
        if road_details is not None:
            params["road_details"] = str(road_details).lower()
        if car_type is not None:
            params["car_type"] = str(car_type)
        if car_fuel is not None:
            params["car_fuel"] = car_fuel
        if car_hipass is not None:
            params["car_hipass"] = str(car_hipass).lower()
        if summary is not None:
            params["summary"] = str(summary).lower()

        return cast(
            Dict[str, Any],
            await self._make_request(
                method="GET",
                base_url=self.KAKAO_MOBILITY_API_BASE_URL,
                endpoint=self.FUTURE_DIRECTIONS_ENDPOINT,
                params=params,
            ),
        )

    async def multi_destination_direction_search(
        self,
        origin: Dict[str, Union[str, float]],
        destinations: List[Dict[str, Union[str, float]]],
        radius: int,
        priority: Optional[Literal["TIME", "DISTANCE"]] = None,
        avoid: Optional[List[str]] = None,
        roadevent: Optional[int] = None,
    ) -> Dict[str, Any]:
        if len(destinations) > 30:
            raise KakaoApiClientError("Maximum 30 destinations allowed")
        if radius > 10000:
            raise KakaoApiClientError("Maximum radius is 10000 meters")

        request_body: Dict[str, Any] = {
            "origin": origin,
            "destinations": destinations,
            "radius": radius,
        }
        if priority is not None:
            request_body["priority"] = priority
        if avoid is not None:
            request_body["avoid"] = avoid
        if roadevent is not None:
            request_body["roadevent"] = roadevent

        return cast(
            Dict[str, Any],
            await self._make_request(
                method="POST",
                base_url=self.KAKAO_MOBILITY_API_BASE_URL,
                endpoint=self.MULTI_DESTINATION_DIRECTIONS_ENDPOINT,
                json_data=request_body,
                use_cache=False,
            ),
        )


async def main():
    api_key = os.environ.get("KAKAO_REST_API_KEY")
    if not api_key:
        print("Please set KAKAO_REST_API_KEY environment variable")
        return

    client = KakaoMapsApiClient(api_key=api_key)
    try:
        result = await client.geocode("서울시 강남구 테헤란로 152")
        print("Geocoding result:", json.dumps(result, indent=2, ensure_ascii=False))
        result = await client.search_by_keyword("카카오")
        print("Keyword search result:", json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await KakaoMapsApiClient.close_all_connections()


if __name__ == "__main__":
    asyncio.run(main())