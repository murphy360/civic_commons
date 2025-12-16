#!/usr/bin/env python3
"""
Script to find the Document Center folder ID for a specific folder name.
Iterates through folder IDs until it finds the matching folder.

Uses Selenium to handle JavaScript-rendered content.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import sys
import time


def setup_driver():
    """Set up headless Chrome driver."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    driver = webdriver.Chrome(options=options)
    return driver


def check_folder(driver, base_url: str, folder_id: int, search_pattern: str, verbose: bool = True) -> dict | None:
    """
    Check if a folder matches the search pattern.
    
    Returns dict with folder info if found, None otherwise.
    """
    url = f"{base_url}/DocumentCenter/Index/{folder_id}"
    
    try:
        driver.get(url)
        
        # Wait for page to load (look for common elements)
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "ul[aria-label], .no-documents, #items-list, h4"))
            )
        except TimeoutException:
            pass
        
        # Small delay for JS to render
        time.sleep(0.5)
        
        # Check for login redirect
        if "cpauthentication.civicplus.com" in driver.current_url:
            if verbose:
                print(f"  [{folder_id}] SKIP - Requires login")
            return None
        
        # Check for 404
        if "Item no longer available" in driver.page_source or "Custom404" in driver.current_url:
            if verbose:
                print(f"  [{folder_id}] DELETED - Item no longer available")
            return None
        
        # Try to find the document list with aria-label
        folder_name = "Unknown"
        doc_count = 0
        sample_docs = []
        
        try:
            # Look for the document list
            doc_list = driver.find_element(By.CSS_SELECTOR, "ul[aria-label]")
            aria_label = doc_list.get_attribute("aria-label")
            if aria_label and aria_label.startswith("Documents for "):
                folder_name = aria_label.replace("Documents for ", "")
            elif aria_label:
                folder_name = aria_label
        except NoSuchElementException:
            pass
        
        # Count and get document links
        try:
            doc_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/DocumentCenter/View/']")
            doc_count = len(doc_links)
            sample_docs = [link.text.strip()[:60] for link in doc_links[:3] if link.text.strip()]
        except NoSuchElementException:
            pass
        
        # Check for "No Documents"
        if "No Documents" in driver.page_source:
            if verbose:
                print(f"  [{folder_id}] EMPTY - {folder_name}")
            if search_pattern.lower() in folder_name.lower():
                return {
                    'folder_id': folder_id,
                    'url': url,
                    'folder_name': folder_name,
                    'document_count': 0,
                    'note': 'Folder exists but is empty'
                }
            return None
        
        if verbose:
            print(f"  [{folder_id}] {folder_name} ({doc_count} docs)")
            if sample_docs:
                print(f"           Sample: {sample_docs[0]}")
        
        # Check if this folder matches our search pattern
        if search_pattern.lower() in folder_name.lower():
            return {
                'folder_id': folder_id,
                'url': url,
                'folder_name': folder_name,
                'document_count': doc_count,
                'sample_docs': sample_docs
            }
        
        # Also check if documents match the pattern (e.g., "-25" for 2025 legislation)
        if doc_count > 0:
            matching_docs = [link for link in doc_links if search_pattern.lower() in link.text.lower()]
            if matching_docs:
                return {
                    'folder_id': folder_id,
                    'url': url,
                    'folder_name': folder_name,
                    'matching_documents': len(matching_docs),
                    'total_documents': doc_count,
                    'sample_docs': [link.text.strip()[:60] for link in matching_docs[:3]]
                }
                
    except Exception as e:
        if verbose:
            print(f"  [{folder_id}] ERROR - {e}")
        return None
    
    return None


def find_folder(base_url: str, search_pattern: str, start_id: int = 1, end_id: int = 500, verbose: bool = True):
    """
    Search for a folder matching the pattern.
    """
    print(f"Searching for '{search_pattern}' in {base_url}/DocumentCenter")
    print(f"Checking folder IDs {start_id} to {end_id}...")
    print("-" * 60)
    
    driver = setup_driver()
    
    try:
        for folder_id in range(start_id, end_id + 1):
            result = check_folder(driver, base_url, folder_id, search_pattern, verbose=verbose)
            
            if result:
                print("\n" + "=" * 60)
                print(f"✓ FOUND MATCHING FOLDER!")
                print("=" * 60)
                for key, value in result.items():
                    print(f"  {key}: {value}")
                print("=" * 60)
                return result
    finally:
        driver.quit()
    
    print(f"\nNo folder found matching '{search_pattern}' in range {start_id}-{end_id}")
    return None


def main():
    # Configuration
    BASE_URL = "https://www.mytwinsburg.com"
    SEARCH_PATTERN = "2025 Legislation"
    
    # Start from known 2024 Legislation folder (375)
    START_ID = 375
    END_ID = 450
    
    # Allow command line overrides
    if len(sys.argv) >= 2:
        SEARCH_PATTERN = sys.argv[1]
    if len(sys.argv) >= 3:
        START_ID = int(sys.argv[2])
    if len(sys.argv) >= 4:
        END_ID = int(sys.argv[3])
    
    print(f"Document Center Folder Finder (Selenium)")
    print(f"Base URL: {BASE_URL}")
    print(f"Search Pattern: {SEARCH_PATTERN}")
    print(f"Range: {START_ID} - {END_ID}")
    print()
    
    result = find_folder(BASE_URL, SEARCH_PATTERN, START_ID, END_ID)
    
    if result:
        print(f"\nUse this folder ID in your configuration: {result['folder_id']}")
        print(f"Direct URL: {result['url']}")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
