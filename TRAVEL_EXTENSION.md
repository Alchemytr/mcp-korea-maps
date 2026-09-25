# Travel extension

This fork adds a travel-focused nearby-place search tool while preserving the upstream MCP server unchanged.

## Added tool

`search_nearby_places`

Searches around a longitude/latitude using Kakao Local API and returns compact results sorted by distance.

Parameters:

- `keyword` — place/business/landmark search term
- `longitude`, `latitude` — search centre
- `radius` — metres, 1–20,000 (default 2,000)
- `category_group_code` — optional Kakao category filter
- `limit` — 1–15 results

Useful Kakao category group codes:

- `FD6` — food
- `CE7` — cafe
- `CS2` — convenience store
- `HP8` — hospital
- `PM9` — pharmacy
- `AT4` — tourist attraction
- `AD5` — accommodation
- `SW8` — subway station
- `OL7` — petrol station

## Run the travel-enabled server

Configure `KAKAO_REST_API_KEY` as described by the upstream project, then run:

```bash
python -m mcp_maps.travel_server
```

`mcp_maps.travel_server` imports the original server, so all upstream MCP tools remain available and `search_nearby_places` is added alongside them.

## Why this is separate

Keeping the travel extension in its own module makes it easier to continue pulling upstream changes without maintaining a large fork-specific patch to the core Kakao client or base server.
