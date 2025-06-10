from dotenv import load_dotenv
import logging
import sys
import requests
import re
from urllib.parse import urlparse
from typing import Optional, Dict
from supabase import create_client, Client
from datetime import datetime, timedelta
import os

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,  # or INFO if you want less noise
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # ensures logs show up in console
    ]
)

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")
clearbit_api_key = os.getenv("CLEARBIT_API_KEY")

class EnhancedCareerPageFinder:
    def __init__(self, local_google_api_key: str, google_cse_id: str):
        self.google_api_key = local_google_api_key
        self.google_cse_id = google_cse_id
        self.clearbit_api_key = clearbit_api_key
        self.google_base_url = "https://www.googleapis.com/customsearch/v1"
        self.clearbit_base_url = "https://company.clearbit.com/v1/domains/find"

        # Initialize client
        self.supabase: Client = create_client(supabase_url, supabase_key)

    # def _setup_database(self):
    #     """Initialize the SQLite database for caching career pages"""
    #     conn = sqlite3.connect(self.db_path)
    #     cursor = conn.cursor()
    #
    #     cursor.execute('''
    #         CREATE TABLE IF NOT EXISTS career_pages (
    #             id BIGSERIAL PRIMARY KEY,
    #             company_name TEXT NOT NULL,
    #             company_domain TEXT,
    #             career_url TEXT,
    #             source TEXT,
    #             confidence_score INTEGER,
    #             created_at TIMESTAMPTZ DEFAULT NOW(),
    #             last_verified TIMESTAMPTZ DEFAULT NOW(),
    #             UNIQUE(company_name)
    #         );
    #     ''')
    #
    #     conn.commit()
    #     conn.close()

    def find_career_page(self, company_name: str, force_refresh: bool = False) -> Optional[Dict]:
        """
        Main function to find career page using layered approach

        Args:
            company_name: Name of the company
            force_refresh: Skip cache and do fresh lookup

        Returns:
            Dict with career_url, domain, source, confidence_score or None
        """
        print(f"🔍 Finding career page for: {company_name}")

        # Step 1: Check database cache first (unless force refresh)
        if not force_refresh:
            cached_result = self._get_from_cache(company_name)
            if cached_result:
                print(f"📋 Found in cache: {cached_result['career_url']}")
                return cached_result

        # Step 2: Try Clearbit domain lookup
        print("🌐 Trying Clearbit domain lookup...")
        company_domain = self._clearbit_domain_lookup(company_name)

        career_result = None

        if company_domain:
            print(f"✅ Clearbit found domain: {company_domain}")
            # Step 3a: Targeted Google search within the domain
            career_result = self._targeted_google_search(company_name, company_domain)

        else:
            print("❌ No domain from Clearbit")

        # Step 3b: Fallback to broad Google search if targeted search failed
        if not career_result:
            print("🔍 Trying broad Google search...")
            career_result = self._broad_google_search(company_name)

        # Step 4: Cache the result
        if career_result:
            self._cache_result(company_name, career_result, company_domain)
            print(f"💾 Cached result for future use")
            return career_result

        print(f"❌ No career page found for {company_name}")
        return None

    def _get_from_cache(self, company_name: str) -> Optional[Dict]:
        """Get cached career page from database"""
        thirty_days_ago = datetime.now() - timedelta(days=30)

        local_result = self.supabase.table('career_pages') \
            .select('company_domain, career_url, source, confidence_score, last_verified') \
            .ilike('company_name', company_name) \
            .gt('last_verified', thirty_days_ago.isoformat()) \
            .execute()

        if local_result.data:
            row = local_result.data[0]
            return {
                'domain': row['company_domain'],
                'career_url': row['career_url'],
                'source': row['source'],
                'confidence_score': row['confidence_score'],
                'last_verified': row['last_verified']
            }

        return None

    def _clearbit_domain_lookup(self, company_name: str) -> Optional[str]:
        """Use Clearbit to find company's official domain"""
        try:
            headers = {
                'Authorization': f'Bearer {self.clearbit_api_key}',
                'Content-Type': 'application/json'
            }

            params = {'name': company_name}

            response = requests.get(
                self.clearbit_base_url,
                headers=headers,
                params=params,
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return data.get('domain')

        except Exception as e:
            print(f"Clearbit error: {e}")

        return None

    def _targeted_google_search(self, company_name: str, domain: str) -> Optional[Dict]:
        """Search for career page within a specific domain"""
        search_queries = [
            f'site:{domain} careers',
            f'site:{domain} jobs',
            f'site:{domain} hiring',
            f'site:{domain} "careers" OR "jobs" OR "hiring"'
        ]

        for query in search_queries:
            print(f"  Trying: {query}")
            results = self._google_search(query)

            if results:
                best_result = self._find_best_career_url(results, company_name, is_targeted=True)
                if best_result:
                    return {
                        'domain': domain,
                        'career_url': best_result['url'],
                        'source': 'targeted_google_clearbit',
                        'confidence_score': best_result['score']
                    }

        return None

    def _broad_google_search(self, company_name: str) -> Optional[Dict]:
        """Broad Google search across the entire web"""
        search_queries = [
            f'"{company_name}" careers',
            f'"{company_name}" jobs',
            f'"{company_name}" careers OR jobs OR hiring'
        ]

        for query in search_queries:
            print(f"  Trying: {query}")
            results = self._google_search(query)

            if results:
                best_result = self._find_best_career_url(results, company_name, is_targeted=False)
                if best_result:
                    domain = urlparse(best_result['url']).netloc
                    return {
                        'domain': domain,
                        'career_url': best_result['url'],
                        'source': 'broad_google',
                        'confidence_score': best_result['score']
                    }

        return None

    def _google_search(self, query: str, num_results: int = 10) -> list:
        """Perform Google Custom Search"""
        params = {
            'key': self.google_api_key,
            'cx': self.google_cse_id,
            'q': query,
            'num': min(num_results, 10)
        }

        try:
            response = requests.get(self.google_base_url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            return data.get('items', [])

        except Exception as e:
            print(f"Google search error: {e}")
            return []

    def _find_best_career_url(self, search_results: list, company_name: str, is_targeted: bool) -> Optional[Dict]:
        """Find the best career URL from search results"""
        scored_results = []

        for result in search_results:
            url = result.get('link', '')
            title = result.get('title', '')
            snippet = result.get('snippet', '')

            score = self._score_career_url(url, title, snippet, company_name, is_targeted)

            if score > 0:
                scored_results.append({
                    'score': score,
                    'url': url,
                    'title': title
                })

        if scored_results:
            best = max(scored_results, key=lambda x: x['score'])
            if best['score'] >= (30 if is_targeted else 50):  # Lower threshold for targeted
                return best

        return None

    def _score_career_url(self, url: str, title: str, snippet: str, company_name: str, is_targeted: bool) -> int:
        """Score a career URL (enhanced for targeted vs broad search)"""
        if not url:
            return 0

        score = 0
        url_lower = url.lower()
        title_lower = title.lower()
        snippet_lower = snippet.lower()
        company_lower = self._clean_company_name(company_name).lower()

        # Exclude job boards
        job_boards = [
            'indeed.com', 'linkedin.com', 'glassdoor.com', 'ziprecruiter.com',
            'monster.com', 'careerbuilder.com', 'simplyhired.com'
        ]

        if any(board in url_lower for board in job_boards):
            return 0

        # Must have career-related keywords
        career_keywords = ['career', 'jobs', 'hiring', 'employment', 'work', 'join']
        has_career_keyword = any(keyword in url_lower or keyword in title_lower
                                 for keyword in career_keywords)

        if not has_career_keyword:
            return 0

        # Scoring (higher for targeted searches since we trust the domain)
        base_multiplier = 1.2 if is_targeted else 1.0

        # URL contains career terms
        if any(term in url_lower for term in ['career', 'jobs', 'hiring']):
            score += int(50 * base_multiplier)

        # Company name in title
        if company_lower in title_lower:
            score += int(75 * base_multiplier)

        # Career URL patterns
        career_patterns = ['/careers', '/jobs', '/hiring', 'careers.', 'jobs.']
        if any(pattern in url_lower for pattern in career_patterns):
            score += int(40 * base_multiplier)

        # Official indicators in title
        official_indicators = ['careers at', 'jobs at', 'work at', 'join our team']
        if any(indicator in title_lower for indicator in official_indicators):
            score += int(60 * base_multiplier)

        # For targeted searches, give bonus for being on the expected domain
        if is_targeted:
            score += 30  # Domain trust bonus

        return score

    def _clean_company_name(self, company_name: str) -> str:
        """Clean company name by removing suffixes"""
        suffixes = ['Inc', 'Inc.', 'LLC', 'Corp', 'Corp.', 'Corporation', 'Ltd', 'Limited', 'Co']

        cleaned = company_name
        for suffix in suffixes:
            pattern = r'\b' + re.escape(suffix) + r'\b\s*$'
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        return cleaned.strip()

    def _cache_result(self, company_name: str, parameter_result: Dict, domain: Optional[str]):
        """Cache the result in database"""
        data = {
            'company_name': company_name,
            'company_domain': domain,
            'career_url': parameter_result['career_url'],
            'source': parameter_result['source'],
            'confidence_score': parameter_result['confidence_score'],
            'last_verified': datetime.now().isoformat()
        }

        # Supabase upsert (INSERT OR REPLACE equivalent)
        self.supabase.table('career_pages') \
            .upsert(data, on_conflict='company_name') \
            .execute()

    def get_cache_stats(self) -> Dict:
        """Get statistics about cached entries"""
        # Get total count
        total_result = self.supabase.table('career_pages') \
            .select('*', count='exact') \
            .execute()

        total_entries = total_result.count

        # Get source breakdown - need to use RPC or aggregate in Python
        # Option 1: Fetch all and group in Python
        source_result = self.supabase.table('career_pages') \
            .select('source') \
            .execute()

        source_breakdown = {}
        for row in source_result.data:
            source = row['source']
            source_breakdown[source] = source_breakdown.get(source, 0) + 1

        return {
            'total_entries': total_entries,
            'source_breakdown': source_breakdown
        }

# # Usage example
# if __name__ == "__main__":
#     google_api_key = os.getenv("GOOGLE_API_KEY")
#     search_engine_id = os.getenv("SEARCH_ENGINE_ID")
#
#
#     finder = EnhancedCareerPageFinder(google_api_key, search_engine_id)
#
#     # Test with different companies
#     test_companies = [
#         "Apple Inc",
#         "Google",
#         "Microsoft Corporation",
#         "Tesla Inc"
#     ]
#
#     for company in test_companies:
#         result = finder.find_career_page(company)
#         if result:
#             print(f"✅ {company}")
#             print(f"   Domain: {result['domain']}")
#             print(f"   Career URL: {result['career_url']}")
#             print(f"   Source: {result['source']}")
#             print(f"   Confidence: {result['confidence_score']}")
#         else:
#             print(f"❌ {company}: No career page found")
#         print("-" * 60)
#
#         # Show cache stats
#     stats = finder.get_cache_stats()
#     print(f"\n📊 Cache Stats: {stats}")