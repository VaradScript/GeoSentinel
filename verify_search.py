from duckduckgo_search import DDGS

print("Verifying Image Search (SafeSearch OFF)...")
try:
    ddgs = DDGS()
    # "porn" query to test safe search is off
    results = ddgs.images("porn", max_results=5, safesearch='off') 
    if results:
        print(f"✅ Image search returned {len(results)} results.")
        print(f"First result title: {results[0].get('title')}")
    else:
        print("❌ Image search returned NO results.")
except Exception as e:
    print(f"❌ Image search failed: {e}")

print("\nVerifying Video Search (SafeSearch OFF + Thumbnails)...")
try:
    results = ddgs.videos("test video", max_results=5, safesearch='off')
    if results:
        print(f"✅ Video search returned {len(results)} results.")
        first = results[0]
        # Check for images/thumbnail structure
        thumb = first.get('images', {}).get('large')
        if thumb:
             print(f"✅ Video thumbnail found: {thumb}")
             print(f"First result title: {first.get('title')}")
        else:
             print("❌ Video thumbnail NOT found in first result.")
             print(f"Result keys: {first.keys()}")
    else:
        print("❌ Video search returned NO results.")
except Exception as e:
    print(f"❌ Video search failed: {e}")
