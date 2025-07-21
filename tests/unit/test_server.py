import pytest
import os
from unittest.mock import patch, AsyncMock

# Import the underlying functions directly
import mcp_maps.server as server_module


class TestServerFunctions:
    """Test cases for MCP server functions."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test environment."""
        # Reset the global API client
        server_module._api_client = None
        # Mock environment variable
        with patch.dict(os.environ, {"KAKAO_REST_API_KEY": "test_api_key"}):
            yield

    @pytest.fixture
    def mock_client(self):
        """Create a mock KakaoMapsApiClient."""
        with patch("mcp_maps.server.KakaoMapsApiClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            yield mock_client

    def test_get_api_client_missing_key(self):
        """Test get_api_client raises error when API key is missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(
                ValueError, match="KAKAO_REST_API_KEY environment variable is required"
            ):
                server_module.get_api_client()

    def test_get_api_client_with_key(self, mock_client):
        """Test get_api_client returns client when API key is present."""
        client = server_module.get_api_client()
        assert client is not None

    @pytest.mark.asyncio
    async def test_geocode_address_success(self, mock_client):
        """Test successful geocoding."""
        # Mock the API response
        mock_response = {
            "meta": {"total_count": 1},
            "documents": [
                {
                    "address_name": "서울 강남구 테헤란로 152",
                    "x": "127.0357821",
                    "y": "37.4996954",
                }
            ],
        }
        mock_client.geocode.return_value = mock_response

        # Get the actual function from the tool
        tools = await server_module.mcp.get_tools()
        geocode_func = tools["geocode_address"].fn

        with patch("mcp_maps.server.get_api_client", return_value=mock_client):
            result = await geocode_func("서울시 강남구 테헤란로 152")

            # Now result is directly a dictionary
            assert isinstance(result, dict)
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_geocode_address_error(self, mock_client):
        """Test geocoding with API error."""
        mock_client.geocode.side_effect = Exception("API Error")

        tools = await server_module.mcp.get_tools()
        geocode_func = tools["geocode_address"].fn

        with patch("mcp_maps.server.get_api_client", return_value=mock_client):
            result = await geocode_func("invalid address")

            # Now result is directly a dictionary
            assert isinstance(result, dict)
            assert "error" in result
            assert result["error"] == "API Error"
            assert result["place_name"] == "invalid address"

    @pytest.mark.asyncio
    async def test_search_places_by_keyword_success(self, mock_client):
        """Test successful place search."""
        mock_response = {
            "meta": {"total_count": 1},
            "documents": [
                {
                    "place_name": "카카오 판교아지트",
                    "x": "127.1086228",
                    "y": "37.4012191",
                }
            ],
        }
        mock_client.search_by_keyword.return_value = mock_response

        tools = await server_module.mcp.get_tools()
        search_func = tools["search_places_by_keyword"].fn

        with patch("mcp_maps.server.get_api_client", return_value=mock_client):
            result = await search_func("카카오")

            # Now result is directly a dictionary
            assert isinstance(result, dict)
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_get_directions_by_coordinates_success(self, mock_client):
        """Test successful directions by coordinates."""
        mock_response = {"routes": [{"summary": {"distance": 7889, "duration": 1200}}]}
        mock_client.direction_search_by_coordinates.return_value = mock_response

        tools = await server_module.mcp.get_tools()
        directions_func = tools["get_directions_by_coordinates"].fn

        with patch("mcp_maps.server.get_api_client", return_value=mock_client):
            result = await directions_func(
                127.0357821, 37.4996954, 127.1086228, 37.4012191
            )

            # Now result is directly a dictionary
            assert isinstance(result, dict)
            assert result == mock_response

    @pytest.mark.asyncio
    async def test_get_future_directions_invalid_priority(self, mock_client):
        """Test future directions with invalid priority."""
        tools = await server_module.mcp.get_tools()
        future_directions_func = tools["get_future_directions"].fn

        with patch("mcp_maps.server.get_api_client", return_value=mock_client):
            result = await future_directions_func(
                127.0357821,
                37.4996954,
                127.1086228,
                37.4012191,
                "2024-12-25T09:00:00",
                priority="INVALID",
            )

            # Now result is directly a dictionary
            assert isinstance(result, dict)
            assert "error" in result
            assert "Priority must be one of" in result["error"]
            assert "origin" in result
            assert "destination" in result
            assert "departure_time" in result

    @pytest.mark.asyncio
    async def test_optimize_multi_destination_route_invalid_json(self, mock_client):
        """Test multi-destination optimization with invalid JSON."""
        tools = await server_module.mcp.get_tools()
        multi_dest_func = tools["optimize_multi_destination_route"].fn

        with patch("mcp_maps.server.get_api_client", return_value=mock_client):
            result = await multi_dest_func(
                127.0357821, 37.4996954, "invalid json", 5000
            )

            # Now result is directly a dictionary
            assert isinstance(result, dict)
            assert "error" in result
            assert "Invalid JSON format" in result["error"]
            assert "origin" in result
            assert "destinations" in result
            assert "radius" in result

    @pytest.mark.asyncio
    async def test_optimize_multi_destination_route_invalid_priority(self, mock_client):
        """Test multi-destination optimization with invalid priority."""
        destinations_json = '[{"key":"dest1","x":127.1086228,"y":37.4012191}]'
        tools = await server_module.mcp.get_tools()
        multi_dest_func = tools["optimize_multi_destination_route"].fn

        with patch("mcp_maps.server.get_api_client", return_value=mock_client):
            result = await multi_dest_func(
                127.0357821, 37.4996954, destinations_json, 5000, "INVALID"
            )

            # Now result is directly a dictionary
            assert isinstance(result, dict)
            assert "error" in result
            assert "Priority must be either" in result["error"]
            assert "origin" in result
            assert "destinations" in result
            assert "radius" in result
