"""
Complete Website Data Extraction Tool

This script performs a comprehensive extraction of ALL data from a website:
- All text content (headings, paragraphs, lists, tables, etc.)
- All images and media
- All links and navigation structures
- All forms and interactive elements
- All metadata and hidden fields
- All structured data
- All downloadable files
- All page layouts and structures

Setup Instructions:
1. Install required packages:
   pip install requests beautifulsoup4 lxml html5lib selenium webdriver-manager

2. Run this script:
   python complete_website_extractor.py
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import time
import re
import base64
from urllib.parse import urljoin, urlparse, parse_qs, unquote
import logging
from datetime import datetime
import hashlib
from collections import deque
import threading
from concurrent.futures import ThreadPoolExecutor
import csv
import shutil
import traceback

# Optional Selenium support for JavaScript-rendered content
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options
    from webdriver_manager.chrome import ChromeDriverManager
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("Selenium not available. Install selenium and webdriver-manager for JavaScript support.")

# ===== CONFIGURATION =====
# Maximum depth to crawl (0 = unlimited)
MAX_CRAWL_DEPTH = 10
# Maximum number of pages to crawl per domain (0 = unlimited)
MAX_PAGES_PER_DOMAIN = 5000
# Delay between requests (in seconds)
REQUEST_DELAY = 1
# Maximum number of concurrent threads
MAX_THREADS = 4
# Respect robots.txt
RESPECT_ROBOTS = True
# Use Selenium for JavaScript rendering (if available)
USE_SELENIUM = True
# File extensions to download (empty set means all)
DOWNLOAD_EXTENSIONS = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt'}
# File extensions to ignore when following links
IGNORE_EXTENSIONS = {'.zip', '.rar', '.exe', '.dmg', '.tar', '.gz', '.mp3', '.mp4', '.avi', '.mov'}
# Output directories
DATA_DIR = "extracted_data"
IMAGES_DIR = "extracted_images"
FILES_DIR = "extracted_files"
LOGS_DIR = "logs"
HTML_DIR = "extracted_html"
# User agent string
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
# ===== END CONFIGURATION =====

# Global variables for tracking
visited_urls = set()
url_queue = deque()
robots_cache = {}
domain_page_count = {}
crawl_stats = {
    'pages_crawled': 0,
    'links_found': 0,
    'images_downloaded': 0,
    'files_downloaded': 0,
    'errors': 0,
    'start_time': None,
    'domains_crawled': set()
}

# Thread-safe lock for shared resources
lock = threading.Lock()

# Set up logging
os.makedirs(LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"{LOGS_DIR}/extractor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

# Create output directories
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(HTML_DIR, exist_ok=True)

# ===== UTILITY FUNCTIONS =====

def get_domain(url):
    """Extract domain from URL"""
    return urlparse(url).netloc

def is_same_domain(url1, url2):
    """Check if two URLs are from the same domain"""
    return get_domain(url1) == get_domain(url2)

def normalize_url(url):
    """Normalize URL for comparison"""
    parsed = urlparse(url)
    # Remove fragment and normalize
    normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    return normalized.lower()

def is_valid_url(url):
    """Check if URL is valid and should be crawled"""
    if not url or not url.startswith(('http://', 'https://')):
        return False

    # Check file extension
    path = urlparse(url).path.lower()
    if any(path.endswith(ext) for ext in IGNORE_EXTENSIONS):
        return False

    return True

def is_downloadable_file(url):
    """Check if URL points to a downloadable file"""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in DOWNLOAD_EXTENSIONS)

def can_crawl_url(url):
    """Check if we can crawl this URL according to robots.txt"""
    if not RESPECT_ROBOTS:
        return True

    domain = get_domain(url)

    # Check cache first
    if domain in robots_cache:
        rp = robots_cache[domain]
    else:
        # Fetch and parse robots.txt
        try:
            from urllib.robotparser import RobotFileParser
            rp = RobotFileParser()
            robots_url = f"{urlparse(url).scheme}://{domain}/robots.txt"
            rp.set_url(robots_url)
            rp.read()
            robots_cache[domain] = rp
        except:
            # If robots.txt can't be fetched, assume we can crawl
            robots_cache[domain] = None
            return True

    if rp is None:
        return True

    return rp.can_fetch(USER_AGENT, url)

def generate_page_id(url):
    """Generate a unique ID for a page"""
    return hashlib.md5(url.encode()).hexdigest()

def safe_filename(filename):
    """Convert a string to a safe filename"""
    # Remove invalid characters
    filename = re.sub(r'[\\/*?:"<>|]', "", filename)
    # Limit length
    if len(filename) > 200:
        name, ext = os.path.splitext(filename)
        filename = name[:200] + ext
    return filename

# ===== SELENIUM FUNCTIONS =====

def setup_selenium():
    """Set up Selenium WebDriver"""
    if not SELENIUM_AVAILABLE or not USE_SELENIUM:
        return None

    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument(f"user-agent={USER_AGENT}")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_page_load_timeout(30)

        logger.info("Selenium WebDriver initialized successfully")
        return driver
    except Exception as e:
        logger.error(f"Failed to initialize Selenium: {e}")
        return None

def get_page_with_selenium(url, driver):
    """Get page content using Selenium for JavaScript rendering"""
    if driver is None:
        return None

    try:
        driver.get(url)
        # Wait for page to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        # Scroll to load lazy content
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)  # Wait for any lazy-loaded content

        # Get the page source after JavaScript execution
        html = driver.page_source
        return html
    except Exception as e:
        logger.error(f"Selenium error for {url}: {e}")
        return None

# ===== WEB SCRAPING FUNCTIONS =====

def make_request(url, timeout=30, stream=False):
    """Make HTTP request with error handling"""
    try:
        headers = {'User-Agent': USER_AGENT}
        response = requests.get(url, headers=headers, timeout=timeout, stream=stream)
        response.raise_for_status()
        return response
    except Exception as e:
        logger.error(f"Request failed for {url}: {e}")
        return None

def extract_all_links(soup, base_url):
    """Extract all links from a page"""
    links = set()

    # Find all anchor tags with href
    for link in soup.find_all('a', href=True):
        href = link['href'].strip()
        if href:
            # Convert relative URLs to absolute
            absolute_url = urljoin(base_url, href)
            if is_valid_url(absolute_url):
                links.add(normalize_url(absolute_url))

    # Find links in forms
    for form in soup.find_all('form', action=True):
        action = form['action'].strip()
        if action:
            absolute_url = urljoin(base_url, action)
            if is_valid_url(absolute_url):
                links.add(normalize_url(absolute_url))

    # Look for JavaScript-generated links (common in ASP.NET sites)
    for script in soup.find_all('script'):
        if script.string:
            # Look for URLs in JavaScript
            js_urls = re.findall(r'["\']([^"\']*\.aspx[^"\']*)["\']', script.string)
            for js_url in js_urls:
                absolute_url = urljoin(base_url, js_url)
                if is_valid_url(absolute_url):
                    links.add(normalize_url(absolute_url))

    # Look for URLs in onclick attributes
    for element in soup.find_all(onclick=True):
        onclick = element['onclick']
        url_matches = re.findall(r'["\']([^"\']*\.aspx[^"\']*)["\']', onclick)
        for url_match in url_matches:
            absolute_url = urljoin(base_url, url_match)
            if is_valid_url(absolute_url):
                links.add(normalize_url(absolute_url))

    # Look for URLs in data attributes
    for element in soup.find_all(attrs={"data-url": True}):
        data_url = element['data-url']
        absolute_url = urljoin(base_url, data_url)
        if is_valid_url(absolute_url):
            links.add(normalize_url(absolute_url))

    return list(links)

def extract_all_images(soup, base_url):
    """Extract all images from a page"""
    images = []

    # Regular img tags
    for img in soup.find_all('img'):
        src = img.get('src')
        if src:
            absolute_url = urljoin(base_url, src)
            image_data = {
                'url': absolute_url,
                'alt': img.get('alt', ''),
                'title': img.get('title', ''),
                'width': img.get('width', ''),
                'height': img.get('height', '')
            }
            images.append(image_data)

    # Background images in style attributes
    for element in soup.find_all(style=True):
        style = element['style']
        bg_images = re.findall(r'background-image:\s*url$$[\'"]?([^\'"]*)[\'"]?$$', style)
        for bg_image in bg_images:
            absolute_url = urljoin(base_url, bg_image)
            image_data = {
                'url': absolute_url,
                'type': 'background',
                'element': element.name
            }
            images.append(image_data)

    # SVG images
    for svg in soup.find_all('svg'):
        svg_data = {
            'type': 'svg',
            'content': str(svg)
        }
        images.append(svg_data)

    return images

def download_image(image_url, page_url, page_id):
    """Download and save an image"""
    try:
        response = make_request(image_url)
        if not response:
            return None

        # Create directory structure
        domain = get_domain(page_url)
        domain_dir = os.path.join(IMAGES_DIR, domain)
        page_dir = os.path.join(domain_dir, page_id)
        os.makedirs(page_dir, exist_ok=True)

        # Generate filename
        parsed_url = urlparse(image_url)
        filename = os.path.basename(parsed_url.path)
        if not filename or '.' not in filename:
            # Generate filename from URL hash
            url_hash = hashlib.md5(image_url.encode()).hexdigest()[:8]
            content_type = response.headers.get('Content-Type', '')
            if 'png' in content_type:
                ext = '.png'
            elif 'gif' in content_type:
                ext = '.gif'
            elif 'svg' in content_type:
                ext = '.svg'
            else:
                ext = '.jpg'
            filename = f"image_{url_hash}{ext}"

        # Ensure filename is safe
        filename = safe_filename(filename)

        # Save image
        image_path = os.path.join(page_dir, filename)
        with open(image_path, 'wb') as f:
            f.write(response.content)

        with lock:
            crawl_stats['images_downloaded'] += 1

        return {
            'url': image_url,
            'local_path': image_path,
            'content_type': response.headers.get('Content-Type', ''),
            'size': len(response.content)
        }
    except Exception as e:
        logger.error(f"Error downloading image {image_url}: {e}")
        return None

def download_file(file_url, page_url):
    """Download and save a file"""
    try:
        response = make_request(file_url, stream=True)
        if not response:
            return None

        # Create directory structure
        domain = get_domain(page_url)
        domain_dir = os.path.join(FILES_DIR, domain)
        os.makedirs(domain_dir, exist_ok=True)

        # Generate filename
        parsed_url = urlparse(file_url)
        filename = unquote(os.path.basename(parsed_url.path))
        if not filename:
            # Generate filename from URL hash
            url_hash = hashlib.md5(file_url.encode()).hexdigest()[:8]
            content_type = response.headers.get('Content-Type', '')
            if 'pdf' in content_type:
                ext = '.pdf'
            elif 'excel' in content_type or 'spreadsheet' in content_type:
                ext = '.xlsx'
            elif 'word' in content_type or 'document' in content_type:
                ext = '.docx'
            elif 'text' in content_type:
                ext = '.txt'
            else:
                ext = '.bin'
            filename = f"file_{url_hash}{ext}"

        # Ensure filename is safe
        filename = safe_filename(filename)

        # Save file
        file_path = os.path.join(domain_dir, filename)
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        with lock:
            crawl_stats['files_downloaded'] += 1

        return {
            'url': file_url,
            'local_path': file_path,
            'content_type': response.headers.get('Content-Type', ''),
            'size': int(response.headers.get('Content-Length', 0))
        }
    except Exception as e:
        logger.error(f"Error downloading file {file_url}: {e}")
        return None

def extract_all_text_content(soup):
    """Extract all text content from a page"""
    # Remove script and style elements
    for script in soup(["script", "style"]):
        script.decompose()

    # Extract text from different elements
    content = {}

    # Title
    title_tag = soup.find('title')
    content['title'] = title_tag.get_text().strip() if title_tag else ''

    # Meta description
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    content['meta_description'] = meta_desc.get('content', '') if meta_desc else ''

    # Headings
    headings = {}
    for i in range(1, 7):
        heading_tags = soup.find_all(f'h{i}')
        headings[f'h{i}'] = [h.get_text().strip() for h in heading_tags]
    content['headings'] = headings

    # Paragraphs
    paragraphs = soup.find_all('p')
    content['paragraphs'] = [p.get_text().strip() for p in paragraphs if p.get_text().strip()]

    # Lists
    lists = []
    for ul in soup.find_all(['ul', 'ol']):
        list_items = [li.get_text().strip() for li in ul.find_all('li')]
        lists.append({
            'type': ul.name,
            'items': list_items
        })
    content['lists'] = lists

    # Tables
    tables = []
    for table in soup.find_all('table'):
        table_data = []
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all(['td', 'th'])
            row_data = [cell.get_text().strip() for cell in cells]
            if row_data:
                table_data.append(row_data)
        if table_data:
            tables.append(table_data)
    content['tables'] = tables

    # Divs with specific classes (common in government sites)
    content_divs = []
    for div in soup.find_all('div', class_=True):
        div_text = div.get_text().strip()
        if div_text and len(div_text) > 20:  # Only capture substantial content
            content_divs.append({
                'class': ' '.join(div.get('class', [])),
                'id': div.get('id', ''),
                'text': div_text
            })
    content['content_divs'] = content_divs

    # Spans with content
    spans = []
    for span in soup.find_all('span'):
        span_text = span.get_text().strip()
        if span_text and len(span_text) > 10:
            spans.append({
                'class': ' '.join(span.get('class', [])),
                'id': span.get('id', ''),
                'text': span_text
            })
    content['spans'] = spans

    # Labels (important for forms)
    labels = []
    for label in soup.find_all('label'):
        label_text = label.get_text().strip()
        if label_text:
            labels.append({
                'for': label.get('for', ''),
                'text': label_text
            })
    content['labels'] = labels

    # Forms (important for government sites)
    forms = []
    for form in soup.find_all('form'):
        form_data = {
            'action': form.get('action', ''),
            'method': form.get('method', ''),
            'id': form.get('id', ''),
            'name': form.get('name', ''),
            'inputs': []
        }
        for input_tag in form.find_all(['input', 'select', 'textarea', 'button']):
            input_data = {
                'type': input_tag.get('type', input_tag.name),
                'name': input_tag.get('name', ''),
                'id': input_tag.get('id', ''),
                'value': input_tag.get('value', ''),
                'placeholder': input_tag.get('placeholder', '')
            }
            # For select elements, get options
            if input_tag.name == 'select':
                options = []
                for option in input_tag.find_all('option'):
                    options.append({
                        'value': option.get('value', ''),
                        'text': option.get_text().strip(),
                        'selected': option.get('selected') is not None
                    })
                input_data['options'] = options

            form_data['inputs'].append(input_data)
        forms.append(form_data)
    content['forms'] = forms

    # Links with text
    link_texts = []
    for a in soup.find_all('a', href=True):
        link_text = a.get_text().strip()
        if link_text:
            link_texts.append({
                'href': a['href'],
                'text': link_text,
                'title': a.get('title', '')
            })
    content['link_texts'] = link_texts

    # All text (fallback)
    content['full_text'] = soup.get_text()

    return content

def extract_structured_data(soup):
    """Extract structured data like JSON-LD, microdata, etc."""
    structured_data = {}

    # JSON-LD
    json_ld_scripts = soup.find_all('script', type='application/ld+json')
    json_ld_data = []
    for script in json_ld_scripts:
        try:
            if script.string:
                data = json.loads(script.string)
                json_ld_data.append(data)
        except:
            pass
    structured_data['json_ld'] = json_ld_data

    # Meta tags
    meta_tags = {}
    for meta in soup.find_all('meta'):
        name = meta.get('name') or meta.get('property') or meta.get('http-equiv')
        content = meta.get('content')
        if name and content:
            meta_tags[name] = content
    structured_data['meta_tags'] = meta_tags

    # Open Graph tags
    og_tags = {}
    for meta in soup.find_all('meta', property=re.compile(r'^og:')):
        og_tags[meta['property']] = meta.get('content', '')
    structured_data['open_graph'] = og_tags

    # Twitter Card tags
    twitter_tags = {}
    for meta in soup.find_all('meta', name=re.compile(r'^twitter:')):
        twitter_tags[meta['name']] = meta.get('content', '')
    structured_data['twitter_card'] = twitter_tags

    # ASP.NET specific data
    viewstate = soup.find('input', {'name': '__VIEWSTATE'})
    if viewstate:
        structured_data['asp_viewstate'] = viewstate.get('value', '')

    eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})
    if eventvalidation:
        structured_data['asp_eventvalidation'] = eventvalidation.get('value', '')

    # Microdata
    microdata = []
    for element in soup.find_all(itemscope=True):
        item_type = element.get('itemtype', '')
        item_id = element.get('itemid', '')
        item_props = {}
        for prop in element.find_all(itemprop=True):
            prop_name = prop.get('itemprop', '')
            prop_value = prop.get('content', '') or prop.get_text().strip()
            item_props[prop_name] = prop_value
        if item_props:
            microdata.append({
                'type': item_type,
                'id': item_id,
                'properties': item_props
            })
    structured_data['microdata'] = microdata

    return structured_data

def extract_page_structure(soup):
    """Extract the structure and layout of the page"""
    structure = {}

    # Document structure
    structure['doctype'] = str(soup.doctype) if soup.doctype else ''
    structure['html_attrs'] = dict(soup.find('html').attrs) if soup.find('html') else {}

    # Head section
    head = soup.find('head')
    if head:
        structure['head'] = {
            'title': head.find('title').get_text() if head.find('title') else '',
            'meta_count': len(head.find_all('meta')),
            'script_count': len(head.find_all('script')),
            'link_count': len(head.find_all('link')),
            'style_count': len(head.find_all('style'))
        }

    # Body structure
    body = soup.find('body')
    if body:
        structure['body'] = {
            'id': body.get('id', ''),
            'class': body.get('class', []),
            'div_count': len(body.find_all('div')),
            'p_count': len(body.find_all('p')),
            'a_count': len(body.find_all('a')),
            'img_count': len(body.find_all('img')),
            'table_count': len(body.find_all('table')),
            'form_count': len(body.find_all('form')),
            'script_count': len(body.find_all('script'))
        }

    # Main layout sections
    layout_sections = {}
    for section_id in ['header', 'footer', 'main', 'nav', 'sidebar', 'content']:
        # Look for elements with this ID or class
        elements = soup.find_all(id=section_id) + soup.find_all(class_=section_id)
        if elements:
            layout_sections[section_id] = {
                'count': len(elements),
                'locations': [elem.name for elem in elements]
            }
    structure['layout_sections'] = layout_sections

    # Navigation structure
    nav_elements = soup.find_all('nav') + soup.find_all(class_='nav') + soup.find_all(class_='navigation') + soup.find_all(id='nav') + soup.find_all(id='navigation')
    navigation = []
    for nav in nav_elements:
        nav_links = []
        for link in nav.find_all('a', href=True):
            nav_links.append({
                'text': link.get_text().strip(),
                'href': link['href']
            })
        if nav_links:
            navigation.append({
                'id': nav.get('id', ''),
                'class': ' '.join(nav.get('class', [])),
                'links': nav_links
            })
    structure['navigation'] = navigation

    return structure

def save_html(html, url, page_id):
    """Save the raw HTML of the page"""
    try:
        domain = get_domain(url)
        domain_dir = os.path.join(HTML_DIR, domain)
        os.makedirs(domain_dir, exist_ok=True)

        filename = f"page_{page_id}.html"
        filepath = os.path.join(domain_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)

        return filepath
    except Exception as e:
        logger.error(f"Error saving HTML for {url}: {e}")
        return None

def scrape_page(url, depth=0, source_url=None, selenium_driver=None):
    """Scrape a single page and extract all data"""
    global crawl_stats, visited_urls, url_queue, domain_page_count

    # Check if we should crawl this URL
    if not can_crawl_url(url):
        logger.info(f"Robots.txt disallows crawling {url}")
        return None

    # Check depth limit
    if MAX_CRAWL_DEPTH > 0 and depth > MAX_CRAWL_DEPTH:
        logger.info(f"Max depth reached for {url}")
        return None

    # Check domain page limit
    domain = get_domain(url)
    with lock:
        if domain not in domain_page_count:
            domain_page_count[domain] = 0

        if MAX_PAGES_PER_DOMAIN > 0 and domain_page_count[domain] >= MAX_PAGES_PER_DOMAIN:
            logger.info(f"Max pages reached for domain {domain}")
            return None

        domain_page_count[domain] += 1
        crawl_stats['pages_crawled'] += 1
        crawl_stats['domains_crawled'].add(domain)

    logger.info(f"Scraping (depth {depth}): {url}")

    # Check if it's a downloadable file
    if is_downloadable_file(url):
        file_data = download_file(url, source_url or url)
        if file_data:
            logger.info(f"Downloaded file: {file_data['local_path']}")
        return None

    # Get page content
    html = None
    response = None

    # Try with Selenium first if available (for JavaScript rendering)
    if selenium_driver is not None:
        html = get_page_with_selenium(url, selenium_driver)

    # Fall back to requests if Selenium failed or isn't available
    if html is None:
        response = make_request(url)
        if not response:
            with lock:
                crawl_stats['errors'] += 1
            return None
        html = response.text

    # Parse HTML
    soup = BeautifulSoup(html, 'html5lib')  # html5lib is more lenient with malformed HTML

    # Generate page ID
    page_id = generate_page_id(url)

    # Save the raw HTML
    html_path = save_html(html, url, page_id)

    # Extract all data
    page_data = {
        'url': url,
        'page_id': page_id,
        'domain': domain,
        'depth': depth,
        'source_url': source_url,
        'html_path': html_path,
        'scraped_at': datetime.now().isoformat()
    }

    if response:
        page_data.update({
            'status_code': response.status_code,
            'content_type': response.headers.get('Content-Type', ''),
            'content_length': len(response.content),
            'response_time': response.elapsed.total_seconds()
        })

    # Extract text content
    page_data['content'] = extract_all_text_content(soup)

    # Extract structured data
    page_data['structured_data'] = extract_structured_data(soup)

    # Extract page structure
    page_data['structure'] = extract_page_structure(soup)

    # Extract links
    links = extract_all_links(soup, url)
    page_data['links'] = links

    with lock:
        crawl_stats['links_found'] += len(links)

    # Extract images
    images = extract_all_images(soup, url)
    page_data['images'] = []

    # Download images
    for i, image in enumerate(images):
        if 'url' in image:  # Skip SVG and other non-URL images
            downloaded_image = download_image(image['url'], url, page_id)
            if downloaded_image:
                image.update(downloaded_image)
        page_data['images'].append(image)

    # Save page data to JSON
    save_page_to_json(page_data)

    # Add new links to queue for crawling
    for link in links:
        normalized_link = normalize_url(link)
        with lock:
            if normalized_link not in visited_urls:
                visited_urls.add(normalized_link)
                # Only add links from the same domain for deep crawling
                if is_same_domain(url, link):
                    url_queue.append((link, depth + 1, url))

    # Add delay to be respectful
    time.sleep(REQUEST_DELAY)

    return page_data

def save_page_to_json(page_data):
    """Save page data to JSON file"""
    try:
        domain = page_data['domain']
        page_id = page_data['page_id']

        # Create directory structure
        domain_dir = os.path.join(DATA_DIR, domain)
        os.makedirs(domain_dir, exist_ok=True)

        # Save individual page
        filename = f"page_{page_id}.json"
        filepath = os.path.join(domain_dir, filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(page_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved page data to {filepath}")
    except Exception as e:
        logger.error(f"Error saving page data to JSON: {e}")

def crawl_worker(selenium_driver=None):
    """Worker function for threaded crawling"""
    while True:
        try:
            # Get next URL from queue
            with lock:
                if not url_queue:
                    break
                url, depth, source_url = url_queue.popleft()

            # Scrape the page
            scrape_page(url, depth, source_url, selenium_driver)

        except Exception as e:
            logger.error(f"Error in crawl worker: {e}")
            logger.error(traceback.format_exc())
            with lock:
                crawl_stats['errors'] += 1

def crawl_website(start_url):
    """Crawl a website starting from the given URL"""
    global crawl_stats, visited_urls, url_queue

    logger.info(f"Starting crawl of {start_url}")

    # Initialize
    normalized_start = normalize_url(start_url)
    visited_urls.add(normalized_start)
    url_queue.append((start_url, 0, None))

    # Set up Selenium if available
    selenium_drivers = []
    if SELENIUM_AVAILABLE and USE_SELENIUM:
        for _ in range(min(MAX_THREADS, 2)):  # Limit Selenium instances
            driver = setup_selenium()
            if driver:
                selenium_drivers.append(driver)

    # Use threading for faster crawling
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        # Submit worker tasks
        futures = []

        # First, submit tasks with Selenium drivers
        for driver in selenium_drivers:
            future = executor.submit(crawl_worker, driver)
            futures.append(future)

        # Then submit regular tasks
        for _ in range(MAX_THREADS - len(selenium_drivers)):
            future = executor.submit(crawl_worker, None)
            futures.append(future)

        # Wait for all workers to complete
        for future in futures:
            future.result()

    # Clean up Selenium drivers
    for driver in selenium_drivers:
        try:
            driver.quit()
        except:
            pass

    logger.info(f"Completed crawling {start_url}")

def save_crawl_summary():
    """Save a summary of the crawl session"""
    summary = {
        'session_id': datetime.now().strftime('%Y%m%d_%H%M%S'),
        'start_time': crawl_stats['start_time'],
        'end_time': datetime.now().isoformat(),
        'duration_seconds': (datetime.now() - datetime.fromisoformat(crawl_stats['start_time'])).total_seconds(),
        'pages_crawled': crawl_stats['pages_crawled'],
        'links_found': crawl_stats['links_found'],
        'images_downloaded': crawl_stats['images_downloaded'],
        'files_downloaded': crawl_stats['files_downloaded'],
        'errors': crawl_stats['errors'],
        'domains_crawled': list(crawl_stats['domains_crawled']),
        'configuration': {
            'max_depth': MAX_CRAWL_DEPTH,
            'max_pages_per_domain': MAX_PAGES_PER_DOMAIN,
            'request_delay': REQUEST_DELAY,
            'max_threads': MAX_THREADS,
            'respect_robots': RESPECT_ROBOTS,
            'use_selenium': USE_SELENIUM and SELENIUM_AVAILABLE
        }
    }

    # Save to JSON
    summary_path = os.path.join(DATA_DIR, f"crawl_summary_{summary['session_id']}.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info(f"Crawl summary saved to {summary_path}")
    return summary

def create_csv_export():
    """Create CSV exports of the scraped data"""
    try:
        # Create export directory
        export_dir = os.path.join(DATA_DIR, "csv_export")
        os.makedirs(export_dir, exist_ok=True)

        # Pages summary
        pages_data = []

        # Iterate through all JSON files
        for domain_dir in os.listdir(DATA_DIR):
            domain_path = os.path.join(DATA_DIR, domain_dir)
            if os.path.isdir(domain_path) and domain_dir != "csv_export":
                for filename in os.listdir(domain_path):
                    if filename.endswith('.json') and filename.startswith('page_'):
                        file_path = os.path.join(domain_path, filename)
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                page_data = json.load(f)

                                # Extract basic page info
                                page_info = {
                                    'url': page_data.get('url', ''),
                                    'page_id': page_data.get('page_id', ''),
                                    'domain': page_data.get('domain', ''),
                                    'title': page_data.get('content', {}).get('title', ''),
                                    'scraped_at': page_data.get('scraped_at', ''),
                                    'depth': page_data.get('depth', 0),
                                    'image_count': len(page_data.get('images', [])),
                                    'link_count': len(page_data.get('links', []))
                                }
                                pages_data.append(page_info)
                        except Exception as e:
                            logger.error(f"Error processing {file_path}: {e}")

        # Write pages data to CSV
        if pages_data:
            pages_csv_path = os.path.join(export_dir, "pages_summary.csv")
            with open(pages_csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=pages_data[0].keys())
                writer.writeheader()
                writer.writerows(pages_data)
            logger.info(f"Created pages summary CSV: {pages_csv_path}")

        # Create other CSV exports as needed
        # ...

        return export_dir
    except Exception as e:
        logger.error(f"Error creating CSV export: {e}")
        return None

def main():
    """Main function"""
    global crawl_stats

    # Initialize crawl stats
    crawl_stats['start_time'] = datetime.now().isoformat()

    # Your specific website to crawl
    websites = [
        "https://fnp-ppn.aadnc-aandc.gc.ca/fnp/Main/Search/SearchFN.aspx?lang=eng",
        "https://fnp-ppn.aadnc-aandc.gc.ca/fnp/Main/Search/FNListGrid.aspx?lang=eng",
        "https://fnp-ppn.aadnc-aandc.gc.ca/fnp/Main/Search/FNListGrid.aspx?lang=eng"
        # Add more websites here if needed
    ]

    logger.info("Starting Complete Website Data Extraction")
    logger.info(f"Configuration: Max depth={MAX_CRAWL_DEPTH}, Max pages per domain={MAX_PAGES_PER_DOMAIN}")

    # Crawl each website
    for website in websites:
        try:
            logger.info(f"Starting extraction of {website}")
            crawl_website(website)
        except Exception as e:
            logger.error(f"Error crawling {website}: {e}")
            logger.error(traceback.format_exc())
            crawl_stats['errors'] += 1

    # Save crawl summary
    summary = save_crawl_summary()

    # Create CSV export
    csv_export_dir = create_csv_export()

    # Print final statistics
    logger.info("=== EXTRACTION COMPLETED ===")
    logger.info(f"Pages crawled: {summary['pages_crawled']}")
    logger.info(f"Links found: {summary['links_found']}")
    logger.info(f"Images downloaded: {summary['images_downloaded']}")
    logger.info(f"Files downloaded: {summary['files_downloaded']}")
    logger.info(f"Domains crawled: {len(summary['domains_crawled'])}")
    logger.info(f"Errors: {summary['errors']}")
    logger.info(f"Duration: {summary['duration_seconds']:.2f} seconds")
    if csv_export_dir:
        logger.info(f"CSV exports created in: {csv_export_dir}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Extraction interrupted by user")
        save_crawl_summary()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
        save_crawl_summary()
