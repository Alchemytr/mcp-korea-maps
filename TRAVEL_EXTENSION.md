# Travel extension

This fork adds a travel-focused nearby-place search tool while preserving the upstream MCP tools.

## Added capability

`search_nearby_places`

Searches around a longitude/latitude using Kakao Local API and returns compact travel-oriented results sorted by distance.

Parameters:

- `keyword` — place/business/landmark search term
- `longitude`, `latitude` — search centre
- `radius` — metres, 1–20,000 (default 2,000)
- `category_group_code` — optional Kakao category filter
- `limit` — 1–15 results

Useful Kakao category group codes include:

- `FD6` — food
- `CE7` — cafe
- `CS2` — convenience store
- `HP8` — hospital
- `PM9` — pharmacy
- `AT4` — tourist attraction

The underlying `KakaoMapsApiClient.search_by_keyword()` also now accepts Kakao's location, radius, category, sorting, page and size parameters.

## Running the travel-enabled server

Set your Kakao REST API key as for the upstream project, then run:

```bash
python -m mcp_maps.travel_server
```

This imports the original server, retaining all existing tools, and registers `search_nearby_places` in addition.

## Example use

A client can ask for pharmacies within 1.5 km of a known coordinate and receive names, addresses, phone numbers, coordinates, distance and Kakao Map links without the full raw Kakao response.
