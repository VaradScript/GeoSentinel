# 🔍 Search Options & Dark Web Documentation

Explore the powerful search capabilities of GeoSentinel, from surface web OSINT to the depths of the dark web. 🕵️‍♂️🔒

## 🌐 Advanced Web Scan

The Advanced Web Scan tool allows you to perform deep OSINT searches across multiple platforms and search engines simultaneously.

### 🛠️ How to Use
- **URL**: `/api/tools/web_scan`
- **Method**: `POST`
- **Parameters**:
    - `query`: Your search term or target.
    - `type`: `text`, `images`, or `all`.
    - `sources`: A list of platforms to target.
    - `aggressive`: Set to `true` for deep scraping of result pages.

### 📱 Supported Sources
You can restrict your search to specific high-value OSINT sources:
- **Social Media**: Twitter, Reddit, Instagram, LinkedIn.
- **Communication**: Telegram, Discord.
- **Developer/Code**: GitHub, StackOverflow.
- **Leaks/Dumps**: Pastebin, BreachForums.
- **General Web**: Multi-engine aggregation (Google, Bing, DuckDuckGo).

### 🚀 Aggressive Mode
When **Aggressive Mode** is enabled, GeoSentinel goes beyond simple search results. It attempts to visit the top result links and extract the actual page content to provide a more comprehensive intelligence briefing.

---

## 🔒 Dark Web Search

GeoSentinel provides integrated access to the dark web, allowing you to search across multiple `.onion` search engines anonymously. 🕶️

### 🛡️ How it Works
1. **Tor Network**: If a Tor proxy is running locally (port 9050), GeoSentinel routes queries through the Tor network to access `.onion` sites directly.
2. **Onion Aggregation**: It queries a vast list of dark web engines, including:
    - Ahmia
    - OnionLand
    - Torgle
    - Torch
    - ...and many others.
3. **Clearnet Fallback**: If Tor is not available locally, the system automatically falls back to the Ahmia clearnet proxy to fetch results.

### 🕵️‍♂️ Accessing Dark Web Results
Results from the dark web are flagged with the `TOR_NETWORK` or `Ahmia_Clearnet` source tag. These links typically end in `.onion` and require a Tor-enabled browser (like Tor Browser) to open.

---
*Unlock the hidden layers of the web with GeoSentinel. 🔍🔒*
