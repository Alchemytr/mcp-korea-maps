import os
import json
import logging
import signal
import atexit
import asyncio
import argparse
from typing import Any, Optional, Literal

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_maps.apis.kakao import KakaoMapsApiClient


# Create an MCP server
mcp = FastMCP(
    name="Korea Maps API",
    dependencies=["httpx", "cachetools", "tenacity", "ratelimit"],
)

# Configure basic logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Lazy initialization of the API client
_api_client: Optional[KakaoMapsApiClient] = None


def get_api_client() -> KakaoMapsApiClient:
    """
    Lazily initialize the API client only when needed.
    Reads configuration from environment variables.
    """
    global _api_client
    if _api_client is None:
        # Get API key from environment variable
        api_key = os.environ.get("KAKAO_REST_API_KEY")

        if not api_key:
            raise ValueError(
                "KAKAO_REST_API_KEY environment variable is required. "
                "Please get your API key from https://developers.kakao.com/"
            )

        # Get configuration from environment variables with defaults
        cache_ttl = int(os.environ.get("MCP_KAKAO_CACHE_TTL", 3600))
        rate_limit_calls = int(os.environ.get("MCP_KAKAO_RATE_LIMIT_CALLS", 10))
        rate_limit_period = int(os.environ.get("MCP_KAKAO_RATE_LIMIT_PERIOD", 1))
        concurrency_limit = int(os.environ.get("MCP_KAKAO_CONCURRENCY_LIMIT", 5))

        logger.info("Initializing KakaoMapsApiClient with:")
        logger.info(f"  Cache TTL: {cache_ttl}s")
        logger.info(f"  Rate Limit: {rate_limit_calls} calls / {rate_limit_period}s")
        logger.info(f"  Concurrency Limit: {concurrency_limit}")

        # Initialize the client
        try:
            _api_client = KakaoMapsApiClient(
                api_key=api_key,
                cache_ttl=cache_ttl,
                rate_limit_calls=rate_limit_calls,
                rate_limit_period=rate_limit_period,
                concurrency_limit=concurrency_limit,
            )
            logger.info("KakaoMapsApiClient initialized successfully")
        except ValueError as e:
            logger.error(f"Failed to initialize KakaoMapsApiClient: {e}")
            raise

    return _api_client


# Resource cleanup functions
def cleanup_resources():
    """
    Clean up resources when the server shuts down.
    This function is called by atexit and signal handlers.
    """
    try:
        # Simple cleanup - just close connections if available
        if (
            hasattr(KakaoMapsApiClient, "_shared_client")
            and KakaoMapsApiClient._shared_client
        ):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(KakaoMapsApiClient.close_all_connections())
                loop.close()
            except Exception:
                pass  # Ignore cleanup errors
    except Exception:
        pass  # Ignore all cleanup errors


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    cleanup_resources()
    exit(0)


# MCP Tools for Kakao Maps API
@mcp.tool
async def geocode_address(
    place_name: str,
) -> dict[str, Any]:
    """
    Convert address or place name to coordinates using Kakao Local API.

    This tool uses Kakao's geocoding service to convert text addresses into geographic coordinates.
    Note: Simple place names like "서울역", "강남역" may not return results through geocoding API,
    but specific addresses work well.

    Args:
        place_name: Address or place name to geocode. Examples:
            - Full addresses: "서울시 강남구 테헤란로 152"
            - Building names: "카카오 판교아지트"
            - Landmark names: "롯데월드타워"

    Returns:
        Dictionary containing geocoding results with the following structure:
        {
            "documents": [
                {
                    "address_name": "서울 강남구 테헤란로 152",
                    "address_type": "ROAD_ADDR",
                    "x": "127.036508620542",  // longitude
                    "y": "37.5000242405515", // latitude
                    "address": {
                        "address_name": "서울 강남구 역삼동 737",
                        "region_1depth_name": "서울",
                        "region_2depth_name": "강남구",
                        "region_3depth_name": "역삼동",
                        // ... more address details
                    },
                    "road_address": {
                        "address_name": "서울 강남구 테헤란로 152",
                        "building_name": "강남파이낸스센터",
                        "zone_no": "06236",
                        // ... more road address details
                    }
                }
            ],
            "meta": {
                "is_end": true,
                "pageable_count": 1,
                "total_count": 1
            }
        }

        If no results found, documents array will be empty with total_count: 0
        If an error occurs, returns a dictionary with "error" and "place_name" fields.
    """
    try:
        # Get the API client lazily
        client = get_api_client()

        # Call the API client and return result directly
        result = await client.geocode(place_name)
        return result
    except Exception as e:
        logger.error(f"Error in geocode_address: {e}")
        return {"error": str(e), "place_name": place_name}


@mcp.tool
async def search_places_by_keyword(
    keyword: str,
) -> dict[str, Any]:
    """
    Search for places by keyword using Kakao Local API.

    This tool searches for places, businesses, and landmarks by keyword. It's more effective
    than geocoding for finding general place names like stations, popular businesses, etc.

    Args:
        keyword: Search keyword. Examples:
            - Business chains: "스타벅스", "맥도날드"
            - Company names: "카카오"
            - Landmarks: "롯데월드", "서울역", "강남역"
            - Categories: "병원", "주유소", "편의점"

    Returns:
        Dictionary containing search results with the following structure:
        {
            "documents": [
                {
                    "id": "26102947",
                    "place_name": "스타벅스 제주용담DT점",
                    "category_name": "음식점 > 카페 > 커피전문점 > 스타벅스",
                    "category_group_code": "CE7",
                    "category_group_name": "카페",
                    "phone": "1522-3232",
                    "address_name": "제주특별자치도 제주시 용담삼동 2572-4",
                    "road_address_name": "제주특별자치도 제주시 서해안로 380",
                    "x": "126.484480056159",  // longitude
                    "y": "33.5124867330564", // latitude
                    "place_url": "http://place.map.kakao.com/26102947",
                    "distance": ""  // empty when no reference point specified
                }
                // ... up to 15 results per page
            ],
            "meta": {
                "total_count": 2427,  // total matching places
                "pageable_count": 45, // max pages available
                "is_end": false,      // more results available
                "same_name": {
                    "keyword": "스타벅스",
                    "region": [],
                    "selected_region": ""
                }
            }
        }

        If an error occurs, returns a dictionary with "error" and "keyword" fields.
    """
    try:
        # Get the API client lazily
        client = get_api_client()

        # Call the API client and return result directly
        result = await client.search_by_keyword(keyword)
        return result
    except Exception as e:
        logger.error(f"Error in search_places_by_keyword: {e}")
        return {"error": str(e), "keyword": keyword}


@mcp.tool
async def get_directions_by_coordinates(
    origin_longitude: float,
    origin_latitude: float,
    dest_longitude: float,
    dest_latitude: float,
) -> dict[str, Any]:
    """
    Get directions between two coordinate points using Kakao Mobility API.

    This tool calculates optimal driving routes between two geographic coordinates,
    providing detailed route information including distance, duration, and turn-by-turn directions.

    Args:
        origin_longitude: Origin longitude (x coordinate). Example: 126.9720419 (Seoul Station)
        origin_latitude: Origin latitude (y coordinate). Example: 37.5546788 (Seoul Station)
        dest_longitude: Destination longitude (x coordinate). Example: 127.0276397 (Gangnam Station)
        dest_latitude: Destination latitude (y coordinate). Example: 37.4979462 (Gangnam Station)

    Returns:
        Dictionary containing detailed route information:
        {
            "trans_id": "0197cad3d0377135acf438afb40466f7",
            "routes": [
                {
                    "result_code": 0,
                    "result_msg": "길찾기 성공",
                    "summary": {
                        "origin": {
                            "name": "",
                            "x": 126.97203047353356,
                            "y": 37.5546779838071
                        },
                        "destination": {
                            "name": "",
                            "x": 127.02763594323153,
                            "y": 37.497941298566055
                        },
                        "distance": 10470,    // total distance in meters
                        "duration": 1485,     // estimated time in seconds
                        "fare": {
                            "taxi": 12500,    // estimated taxi fare in KRW
                            "toll": 0         // toll fees in KRW
                        },
                        "bound": {            // bounding box of the route
                            "min_x": 126.9724789262167,
                            "min_y": 37.4914734057364,
                            "max_x": 127.02690448926087,
                            "max_y": 37.55514299549246
                        }
                    },
                    "sections": [
                        {
                            "distance": 10470,
                            "duration": 1485,
                            "roads": [
                                {
                                    "name": "백범로",
                                    "distance": 1214,
                                    "duration": 145,
                                    "traffic_speed": 18.0,  // km/h
                                    "traffic_state": 2,      // 0:원활, 1:서행, 2:지체, 3:정체
                                    "vertexes": [            // route coordinates
                                        126.97386431252335, 37.53566388027694,
                                        126.97409181808435, 37.53557575239915
                                        // ... more coordinate pairs
                                    ]
                                }
                                // ... more road segments
                            ],
                            "guides": [
                                {
                                    "name": "출발지",
                                    "x": 126.97205310639792,
                                    "y": 37.554678180859796,
                                    "distance": 0,
                                    "duration": 0,
                                    "type": 100,           // guide type (100: start, 101: end)
                                    "guidance": "출발지",
                                    "road_index": 0
                                },
                                {
                                    "name": "",
                                    "x": 126.972090149457,
                                    "y": 37.554453242670455,
                                    "distance": 25,
                                    "duration": 6,
                                    "type": 2,             // 1:좌회전, 2:우회전, 3:유턴, etc.
                                    "guidance": "우회전",
                                    "road_index": 1
                                }
                                // ... more turn-by-turn directions
                            ]
                        }
                    ]
                }
            ]
        }

        If an error occurs, returns a dictionary with "error", "origin", and "destination" fields.
    """
    try:
        # Get the API client lazily
        client = get_api_client()

        # Call the API client and return result directly
        result = await client.direction_search_by_coordinates(
            origin_longitude, origin_latitude, dest_longitude, dest_latitude
        )
        return result
    except Exception as e:
        logger.error(f"Error in get_directions_by_coordinates: {e}")
        return {
            "error": str(e),
            "origin": f"{origin_longitude},{origin_latitude}",
            "destination": f"{dest_longitude},{dest_latitude}",
        }


@mcp.tool
async def get_directions_by_address(
    origin_address: str,
    dest_address: str,
) -> dict[str, Any]:
    """
    Get directions between two addresses using Kakao Mobility API.

    This tool first converts addresses to coordinates using geocoding (with keyword search fallback),
    then calculates the optimal driving route. It handles both specific addresses and general place names.

    Args:
        origin_address: Origin address or place name. Examples:
            - Station names: "서울역", "강남역"
            - Specific addresses: "서울시 강남구 테헤란로 152"
            - Building names: "카카오 판교아지트"
            - Landmarks: "롯데월드타워"
        dest_address: Destination address or place name (same format as origin)

    Returns:
        Dictionary containing route information with same structure as get_directions_by_coordinates.

        Example successful response for "서울역" to "강남역":
        {
            "trans_id": "0197cad3d31e728ea9d5bdde19eb3923",
            "routes": [
                {
                    "result_code": 0,
                    "result_msg": "길찾기 성공",
                    "summary": {
                        "distance": 10718,    // meters
                        "duration": 1668,     // seconds (~28 minutes)
                        "fare": {
                            "taxi": 13000,
                            "toll": 0
                        }
                        // ... same structure as coordinate-based directions
                    }
                    // ... detailed route sections and guides
                }
            ]
        }

        Error cases:
        - If address cannot be found: returns dictionary with "error", "origin_address", and "dest_address" fields
        - If no route available: returns error from routing API

        Note: This tool automatically falls back to keyword search if geocoding fails,
        making it more reliable for finding common place names.
    """
    try:
        # Get the API client lazily
        client = get_api_client()

        # Call the API client and return result directly
        result = await client.direction_search_by_address(origin_address, dest_address)
        return result
    except Exception as e:
        logger.error(f"Error in get_directions_by_address: {e}")
        return {
            "error": str(e),
            "origin_address": origin_address,
            "dest_address": dest_address,
        }


@mcp.tool
async def get_future_directions(
    origin_longitude: float,
    origin_latitude: float,
    destination_longitude: float,
    destination_latitude: float,
    departure_time: str,
    priority: Literal["RECOMMEND", "TIME", "DISTANCE"] | None = None,
    alternatives: bool | None = None,
    avoid: str | None = None,
    car_type: int | None = None,
    car_fuel: Literal["GASOLINE", "DIESEL", "LPG"] | None = None,
    car_hipass: bool | None = None,
) -> dict[str, Any]:
    """
    Get future directions with departure time using Kakao Mobility API.

    This tool calculates routes with traffic predictions for a specific future departure time,
    providing more accurate travel time estimates based on expected traffic conditions.

    Args:
        origin_longitude: Origin longitude coordinate
        origin_latitude: Origin latitude coordinate
        destination_longitude: Destination longitude coordinate
        destination_latitude: Destination latitude coordinate
        departure_time: Departure time in yyyyMMddHHmm format (e.g., "202507030900" for July 3, 2025 09:00)
                       Note: API requires this specific format, not ISO format
        priority: Route optimization priority:
            - "RECOMMEND": Balanced route (default)
            - "TIME": Fastest route
            - "DISTANCE": Shortest route
        alternatives: Whether to return alternative routes (boolean)
        avoid: Roads to avoid (comma-separated: "toll", "highway", "ferry")
        car_type: Vehicle type (0-7):
            - 0: General car
            - 1: Midsize car
            - 2: Compact car
            - 3-7: Various commercial vehicles
        car_fuel: Fuel type for cost calculation:
            - "GASOLINE": Gasoline vehicle
            - "DIESEL": Diesel vehicle
            - "LPG": LPG vehicle
        car_hipass: Whether vehicle has Hi-Pass for toll roads (boolean)

    Returns:
        Dictionary containing future route information with traffic predictions:
        {
            "trans_id": "0197cad3d3a07950848fd42a326576a2",
            "routes": [
                {
                    "result_code": 0,
                    "result_msg": "길찾기 성공",
                    "summary": {
                        "origin": {"x": 126.97203047353356, "y": 37.5546779838071},
                        "destination": {"x": 127.02763594323153, "y": 37.497941298566055},
                        "distance": 10467,     // meters
                        "duration": 1552,      // predicted seconds with future traffic
                        "priority": "RECOMMEND",
                        "fare": {
                            "taxi": 12500,
                            "toll": 0
                        }
                    },
                    "sections": [
                        {
                            "roads": [
                                {
                                    "name": "백범로",
                                    "distance": 1214,
                                    "duration": 169,           // predicted time
                                    "traffic_speed": 18.0,     // predicted speed km/h
                                    "traffic_state": 2         // predicted traffic state
                                }
                                // ... more road segments with traffic predictions
                            ]
                        }
                    ]
                }
            ]
        }

        Example usage:
        - departure_time="202507030900" for July 3, 2025 at 9:00 AM
        - duration will reflect expected traffic at that time

        If an error occurs, returns a dictionary with "error", "origin", "destination", and "departure_time" fields.
    """
    try:
        # Get the API client lazily
        client = get_api_client()

        # Validate priority if provided
        if priority and priority not in ["RECOMMEND", "TIME", "DISTANCE"]:
            raise ValueError("Priority must be one of: RECOMMEND, TIME, DISTANCE")

        # Validate car_fuel if provided
        if car_fuel and car_fuel not in ["GASOLINE", "DIESEL", "LPG"]:
            raise ValueError("Car fuel must be one of: GASOLINE, DIESEL, LPG")

        # Call the API client and return result directly
        result = await client.future_direction_search_by_coordinates(
            origin_longitude=origin_longitude,
            origin_latitude=origin_latitude,
            destination_longitude=destination_longitude,
            destination_latitude=destination_latitude,
            departure_time=departure_time,
            priority=priority,
            alternatives=alternatives,
            avoid=avoid,
            car_type=car_type,
            car_fuel=car_fuel,
            car_hipass=car_hipass,
        )
        return result
    except Exception as e:
        logger.error(f"Error in get_future_directions: {e}")
        return {
            "error": str(e),
            "origin": f"{origin_longitude},{origin_latitude}",
            "destination": f"{destination_longitude},{destination_latitude}",
            "departure_time": departure_time,
        }


@mcp.tool
async def optimize_multi_destination_route(
    origin_longitude: float,
    origin_latitude: float,
    destinations: str,
    radius: int = 5000,
    priority: Literal["TIME", "DISTANCE"] | None = None,
) -> dict[str, Any]:
    """
    Optimize routes to multiple destinations using Kakao Mobility API.

    This tool calculates the optimal routes from a single origin to multiple destinations,
    helping to minimize total travel time or distance for delivery routes, multi-stop trips, etc.

    Args:
        origin_longitude: Starting point longitude coordinate
        origin_latitude: Starting point latitude coordinate
        destinations: JSON string array of destination objects. Each destination must have:
            - "key": Unique identifier for the destination (string)
            - "x": Longitude coordinate (number)
            - "y": Latitude coordinate (number)

            Example: '[{"key":"gangnam","x":127.0276397,"y":37.4979462},{"key":"hongik","x":126.9259417,"y":37.5565194}]'

            Maximum 30 destinations allowed.
        radius: Search radius in meters for route optimization (max 10000, default: 5000)
        priority: Optimization criterion:
            - "TIME": Minimize total travel time
            - "DISTANCE": Minimize total distance

    Returns:
        Dictionary containing optimized route information for each destination:
        {
            "trans_id": "0197cad3d4177de2b9e304f1800ef2e0",
            "routes": [
                {
                    "result_code": 0,
                    "result_msg": "길찾기 성공",
                    "key": "gangnam",              // matches destination key
                    "summary": {
                        "distance": 10467,         // meters to this destination
                        "duration": 1925           // seconds to this destination
                    }
                },
                {
                    "result_code": 0,
                    "result_msg": "길찾기 성공",
                    "key": "hongik",
                    "summary": {
                        "distance": 6814,
                        "duration": 1920
                    }
                },
                {
                    "result_code": 0,
                    "result_msg": "길찾기 성공",
                    "key": "itaewon",
                    "summary": {
                        "distance": 4056,
                        "duration": 1028
                    }
                }
            ]
        }

        Use cases:
        - Delivery route optimization
        - Multi-stop trip planning
        - Service area coverage analysis

        Note: Results show individual routes from origin to each destination,
        not a single optimized path visiting all destinations in sequence.

        If an error occurs, returns a dictionary with "error", "origin", "destinations", and "radius" fields.
    """
    try:
        # Get the API client lazily
        client = get_api_client()

        # Parse destinations JSON
        try:
            destinations_list = json.loads(destinations)
            if not isinstance(destinations_list, list):
                raise ValueError("Destinations must be a JSON array")
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format for destinations")

        # Validate destinations format
        for i, dest in enumerate(destinations_list):
            if not isinstance(dest, dict):
                raise ValueError(f"Destination {i} must be an object")
            if not all(key in dest for key in ["key", "x", "y"]):
                raise ValueError(f"Destination {i} must have 'key', 'x', 'y' fields")

        # Validate priority if provided
        if priority and priority not in ["TIME", "DISTANCE"]:
            raise ValueError("Priority must be either 'TIME' or 'DISTANCE'")

        # Prepare origin
        origin: dict[str, float | str] = {
            "x": origin_longitude,
            "y": origin_latitude,
        }

        # Call the API client and return result directly
        result = await client.multi_destination_direction_search(
            origin=origin,
            destinations=destinations_list,
            radius=radius,
            priority=priority,
        )
        return result
    except Exception as e:
        logger.error(f"Error in optimize_multi_destination_route: {e}")
        return {
            "error": str(e),
            "origin": f"{origin_longitude},{origin_latitude}",
            "destinations": destinations,
            "radius": radius,
        }


# Add health check endpoint for HTTP transports
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for monitoring and load balancers."""
    try:
        # Try to get the API client to verify configuration
        get_api_client()
        return JSONResponse(
            {
                "status": "healthy",
                "service": "Korea Maps API MCP Server",
                "timestamp": asyncio.get_event_loop().time(),
                "api_client": "initialized",
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            {
                "status": "unhealthy",
                "service": "Korea Maps API MCP Server",
                "error": str(e),
                "timestamp": asyncio.get_event_loop().time(),
            },
            status_code=503,
        )


def parse_server_config(args: list[str] | None = None) -> tuple[str, dict[str, Any]]:
    """
    Parse server configuration from command line arguments and environment variables.

    Args:
        args: Command line arguments list. If None, uses sys.argv.

    Returns:
        Tuple of (transport, http_config) where:
        - transport: The selected transport protocol
        - http_config: Dictionary of HTTP configuration options (empty for stdio)
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Korea Maps API MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default=None,
        help="Transport protocol to use (default: from environment or stdio)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host address for HTTP transports (default: from environment or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for HTTP transports (default: from environment or 8000)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="Log level for the server (default: from environment or INFO)",
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Path for HTTP endpoints (default: from environment or /mcp)",
    )

    parsed_args = parser.parse_args(args)

    # Determine transport and configuration from args or environment variables
    transport = parsed_args.transport or os.environ.get("MCP_TRANSPORT", "stdio")

    # Configuration for HTTP transports
    http_config = {}
    if transport in ["streamable-http", "sse"]:
        host = parsed_args.host or os.environ.get("MCP_HOST", "127.0.0.1")
        port = parsed_args.port or int(os.environ.get("MCP_PORT", 8000))
        path = parsed_args.path or os.environ.get("MCP_PATH", "/mcp")

        http_config = {
            "host": host,
            "port": port,
            "path": path,
        }

    # Set log level
    log_level = parsed_args.log_level or os.environ.get("MCP_LOG_LEVEL", "INFO")
    logging.getLogger().setLevel(getattr(logging, log_level))

    return transport, http_config


def run_server(transport: str, http_config: dict[str, Any]) -> None:
    """
    Run the MCP server with the given configuration.

    Args:
        transport: Transport protocol to use
        http_config: HTTP configuration dictionary
    """
    # Log the configuration
    logger.info(f"Starting Korea Maps API MCP Server with transport: {transport}")
    if http_config:
        logger.info(f"HTTP configuration: {http_config}")

    try:
        if transport == "stdio":
            logger.info("Using stdio transport - connect via MCP client")
            mcp.run(transport="stdio")
        elif transport in ["streamable-http", "sse"]:
            logger.info(
                f"Using {transport} transport on http://{http_config['host']}:{http_config['port']}{http_config.get('path', '/mcp')}"
            )
            mcp.run(transport=transport, **http_config)
        else:
            logger.error(f"Unsupported transport: {transport}")
            raise ValueError(f"Unsupported transport: {transport}")
    except KeyboardInterrupt:
        logger.info("Server interrupted by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


if __name__ == "__main__":
    # Register cleanup handlers
    atexit.register(cleanup_resources)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Parse configuration and run server
    transport, http_config = parse_server_config()
    run_server(transport, http_config)
