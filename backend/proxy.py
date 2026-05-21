import httpx
import asyncio
from fastapi import Response, Request
from urllib.parse import urljoin, urlparse

async def proxy_request(url: str, request: Request):
    """
    Fetches a URL and returns it as a Response, stripping standard 
    frame-blocking headers to allow embedding in an iframe.
    Switched to httpx for better Windows proactor loop compatibility.
    """
    if not url.startswith("http"):
        url = f"https://{url}"
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
        
    try:
        async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=20.0) as client:
            resp = await client.get(url, headers=headers)
            
            # Create FastAPI response
            response = Response(content=resp.content, status_code=resp.status_code)
            
            # Copy headers and strip security ones
            for k, v in resp.headers.items():
                lower_k = k.lower()
                if lower_k in ["x-frame-options", "content-security-policy", "x-content-security-policy", "frame-options", "content-length"]:
                    continue
                response.headers[k] = v
            
            # Force allow iframe
            response.headers["X-Frame-Options"] = "ALLOWALL"
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Content-Security-Policy"] = "frame-ancestors *;"
            
            return response
    except httpx.TimeoutException:
        return Response(content="Proxy Error: Request timed out. The site might be blocking the engine.", status_code=504)
    except Exception as e:
        print(f"Proxy Internal Error for {url}: {e}")
        return Response(content=f"Proxy Error: {str(e)}", status_code=500)
