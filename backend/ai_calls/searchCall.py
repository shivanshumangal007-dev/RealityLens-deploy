from . import aiCalls


def searchCall(extraction):
    """Perform web/image searches for the provided extraction dict and
    return formatted search text.

    Args:
        extraction (dict): result from extractionCall containing claim and
            other metadata.
    Returns:
        str: formatted search results text.
    """
    claim = extraction.get("claim", "")
    print(f"🌐 Phase 2: Searching for — {claim}")
    entities = extraction.get("claim_entities", claim)
    search_query = entities if entities else claim

    try:
        search_results = aiCalls.tavily_search(search_query, num_results=5)
    except Exception as e:
        if "API key" in str(e):
            print(f"⚠️ Tavily search failed due to API key issue: {e}")
            search_results = aiCalls.parallel_search(search_query)
        else:
            print(f"⚠️ Tavily search error: {e}")
            search_results = aiCalls.parallel_search(search_query)

    if extraction.get("has_embedded_image") and extraction.get("image_description"):
        print("🖼️ Searching for image origin...")
        try:
            image_results = aiCalls.parallel_search(extraction["image_description"], num_results=3)
        except Exception as e:
            print(f"⚠️ Image search error: {e}")
            image_results = aiCalls.tavily_search(extraction["image_description"], num_results=3)

        search_results += image_results

    search_text = aiCalls.format_search_results(search_results)
    print(f"📰 Found {len(search_results)} search results")

    return search_text