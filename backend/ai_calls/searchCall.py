import concurrent.futures
from . import aiCalls


#function for search call
def searchCall(extraction):
    """Perform web/image searches for the provided extraction dict and
    return formatted search text.

    Args:
        extraction (dict): result from extractionCall containing claim and
            other metadata.
    Returns:
        str: formatted search results text.
    """
    #get the claim and entities from the extraction
    claim = extraction.get("claim", "")
    print(f"🌐 Phase 2: Searching for — {claim}")
    entities = extraction.get("claim_entities", claim)
    #set the search query 
    search_query = entities if entities else claim

    def do_text_search():
        #call tavily search or parallel search if tavily fails
        try:
            return aiCalls.tavily_search(search_query, num_results=5)
        except Exception as e:
            #if tavily fails, parallel is faster from what i have seen but its unreliable because it gives claims that are not from credible sources and our scoring relies on the quality of sources 
            if "API key" in str(e):
                print(f"⚠️ Tavily search failed due to API key issue: {e}")
                return aiCalls.parallel_search(search_query)
            else:
                print(f"⚠️ Tavily search error: {e}")
                return aiCalls.parallel_search(search_query)

    def do_image_search():
        #if there is an embedded image and image description
        if extraction.get("has_embedded_image") and extraction.get("image_description"):
            print("🖼️ Searching for image origin...")
            try:
                return aiCalls.tavily_search(extraction["image_description"], num_results=3)
            except Exception as e:
                print(f"⚠️ Image search error: {e}")
                return aiCalls.parallel_search(extraction["image_description"], num_results=3)
        return []
    #run both text and image search in parallel to make the fastest step in the process even faster (idk)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_text = executor.submit(do_text_search)
        future_image = executor.submit(do_image_search)

        search_results = future_text.result()
        image_results = future_image.result()

    search_results += image_results

    search_text = aiCalls.format_search_results(search_results)
    print(f"📰 Found {len(search_results)} search results")

    return search_text