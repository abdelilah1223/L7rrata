from bs4 import BeautifulSoup
import lxml
import extruct
from scrapy.selector import Selector
import requests
import json

def scrape_html(html_content, url):
    """
    Extracts basic information from HTML content.
    """
    soup = BeautifulSoup(html_content, 'lxml')
    selector = Selector(text=html_content)
    
    # Extract metadata using Extruct
    metadata = {}
    try:
        metadata = extruct.extract(html_content, base_url=url)
    except Exception as e:
        print(f"Extruct error: {e}")
        
    # Example logic: extract links
    links = []
    for a in soup.find_all('a', href=True):
        links.append({
            "text": a.text.strip(),
            "href": a['href']
        })
        
    # Scrapy-style extraction example
    title = selector.css('title::text').get()
    
    return {
        "title": title,
        "metadata": metadata,
        "links": links
    }

async def scrape_page(page):
    """
    Scrapes the content of a Playwright page.
    """
    content = await page.content()
    url = page.url
    return scrape_html(content, url)
