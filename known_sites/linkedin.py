import json
from typing import List, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import re
from schema import JobAnalysisResponse, Skill
from known_sites.base_class import JobSiteParser

class LinkedInParser(JobSiteParser):
    """Parser for LinkedIn job postings"""

    def can_parse(self, url: str) -> bool:
        if not url:
            return False
        domain = urlparse(url).netloc.lower()
        return 'linkedin.com' in domain

    def parse(self, content: str, url: Optional[str] = None) -> JobAnalysisResponse:
        soup = BeautifulSoup(content, 'html.parser')

        # Extract job title
        job_title = self._extract_job_title(soup)

        # Extract company name
        company_name = self._extract_company_name(soup)

        # Extract skills and requirements
        skills = self._extract_skills(soup)

        # Extract experience level
        experience_level = self._extract_experience_level(soup)

        # Extract keywords
        keywords = self._extract_keywords(soup)

        # Additional details
        additional_details = {
            "location": self._extract_location(soup),
            "employment_type": self._extract_employment_type(soup),
            "seniority_level": self._extract_seniority_level(soup),
            "company_size": self._extract_company_size(soup)
        }

        return JobAnalysisResponse(
            success=True,
            company_name=company_name,
            job_title=job_title,
            companyUrl=None,
            keywords=keywords,
            skills=skills,
            experience_level=experience_level,
            additional_details=additional_details,
            confidence_scores={"parsing": 0.95}  # High confidence for structured parsing
        )

    def _extract_job_title(self, soup: BeautifulSoup) -> Optional[str]:
        # LinkedIn job title selectors
        selectors = [
            'h1.top-card-layout__title',
            '.job-details-jobs-unified-top-card__job-title h1',
            '.jobs-unified-top-card__job-title h1'
        ]

        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                return element.get_text(strip=True)
        return None

    # def _extract_company_name(self, soup: BeautifulSoup) -> Optional[str]:
    #     selectors = [
    #         '.job-details-jobs-unified-top-card__company-name a',
    #         '.jobs-unified-top-card__company-name a',
    #         '.topcard__org-name-link',
    #         '.job-details-jobs-unified-top-card__primary-description-container a'
    #     ]
    #
    #     for selector in selectors:
    #         element = soup.select_one(selector)
    #         if element:
    #             return element.get_text(strip=True)
    #     return None

    def _extract_skills(self, soup: BeautifulSoup) -> List[Skill]:
        skills = []

        # Look for skills in job description
        description = soup.select_one('.jobs-box__html-content, .job-details-jobs-unified-top-card__job-description')
        if not description:
            return skills

        text = description.get_text().lower()

        # Common tech skills to look for
        tech_skills = [
            'python', 'javascript', 'java', 'react', 'angular', 'vue', 'node.js',
            'sql', 'postgresql', 'mysql', 'mongodb', 'redis', 'docker', 'kubernetes',
            'aws', 'azure', 'gcp', 'git', 'jenkins', 'ci/cd', 'rest api', 'graphql'
        ]

        for skill in tech_skills:
            if skill in text:
                # Try to extract years of experience
                years_pattern = rf'(\d+)\+?\s*years?\s*(?:of\s*)?(?:experience\s*)?(?:with\s*|in\s*)?{re.escape(skill)}'
                years_match = re.search(years_pattern, text, re.IGNORECASE)
                years_exp = years_match.group(1) + "+ years" if years_match else None

                # Check if it's required (look for "required", "must have", etc.)
                is_required = any(req_word in text for req_word in ['required', 'must have', 'essential'])

                skills.append(Skill(
                    name=skill.title(),
                    years_experience=years_exp,
                    is_required=is_required
                ))

        return skills

    def _extract_experience_level(self, soup: BeautifulSoup) -> Optional[str]:
        # Look for seniority level indicators
        text = soup.get_text().lower()

        if any(word in text for word in ['senior', 'sr.', 'lead', 'principal']):
            return "Senior"
        elif any(word in text for word in ['junior', 'jr.', 'entry level', 'graduate']):
            return "Junior"
        elif any(word in text for word in ['mid-level', 'intermediate', '3-5 years']):
            return "Mid-Level"

        return "Not specified"

    def _extract_keywords(self, soup: BeautifulSoup) -> List[str]:
        # Extract key terms from job description
        description = soup.select_one('.jobs-box__html-content, .job-details-jobs-unified-top-card__job-description')
        if not description:
            return []

        text = description.get_text()
        # Simple keyword extraction - you can make this more sophisticated
        common_keywords = [
            'remote', 'hybrid', 'full-time', 'part-time', 'contract',
            'startup', 'enterprise', 'agile', 'scrum', 'team lead'
        ]

        return [keyword for keyword in common_keywords if keyword.lower() in text.lower()]

    def _extract_location(self, soup: BeautifulSoup) -> Optional[str]:
        selectors = [
            '.job-details-jobs-unified-top-card__bullet',
            '.jobs-unified-top-card__bullet'
        ]

        for selector in selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text(strip=True)
                if any(word in text.lower() for word in ['remote', 'hybrid']) or ',' in text:
                    return text
        return None

    def _extract_employment_type(self, soup: BeautifulSoup) -> Optional[str]:
        text = soup.get_text().lower()
        if 'full-time' in text:
            return "Full-time"
        elif 'part-time' in text:
            return "Part-time"
        elif 'contract' in text:
            return "Contract"
        elif 'internship' in text:
            return "Internship"
        return None

    def _extract_seniority_level(self, soup: BeautifulSoup) -> Optional[str]:
        selectors = ['.job-details-jobs-unified-top-card__job-insight']

        for selector in selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text().lower()
                if 'seniority level' in text:
                    return element.get_text(strip=True).split(':')[-1].strip()
        return None

    def _extract_company_size(self, soup: BeautifulSoup) -> Optional[str]:
        # This might require additional API calls or be in company profile
        return None

    def _extract_company_name(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract company name using multiple fallback methods
        """
        # Method 1: JSON-LD structured data (most reliable)
        company_name = self._extract_from_json_ld(soup)
        if company_name:
            return company_name

        # Method 2: Updated CSS selectors (2024/2025)
        company_name = self._extract_from_css_selectors(soup)
        if company_name:
            return company_name

        # Method 3: Meta tags and page title
        company_name = self._extract_from_meta_tags(soup)
        if company_name:
            return company_name

        # Method 4: Text pattern matching
        company_name = self._extract_from_text_patterns(soup)
        if company_name:
            return company_name

        return None

    def _extract_from_json_ld(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract company name from JSON-LD structured data
        """
        try:
            # Find all script tags with application/ld+json
            json_scripts = soup.find_all('script', {'type': 'application/ld+json'})

            for script in json_scripts:
                if script.string:
                    try:
                        data = json.loads(script.string)

                        # Handle different JSON-LD structures
                        if isinstance(data, dict):
                            # Look for company/organization info
                            company_name = self._extract_company_from_json_object(data)
                            if company_name:
                                return company_name

                        elif isinstance(data, list):
                            # Handle array of JSON-LD objects
                            for item in data:
                                if isinstance(item, dict):
                                    company_name = self._extract_company_from_json_object(item)
                                    if company_name:
                                        return company_name

                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            print(f"Error extracting from JSON-LD: {e}")

        return None

    def _extract_company_from_json_object(self, data: dict) -> Optional[str]:
        """
        Extract company name from a JSON-LD object
        """
        # Common patterns in LinkedIn JSON-LD
        company_paths = [
            'hiringOrganization.name',
            'hiringOrganization.legalName',
            'employmentType.hiringOrganization.name',
            'publisher.name',
            'author.name',
            'organization.name',
            'company.name',
            'employer.name'
        ]

        for path in company_paths:
            value = self._get_nested_value(data, path)
            if value and isinstance(value, str) and len(value.strip()) > 0:
                return value.strip()

        # Also check top-level keys
        direct_keys = ['companyName', 'company', 'employer', 'organization']
        for key in direct_keys:
            if key in data and isinstance(data[key], str):
                return data[key].strip()
            elif key in data and isinstance(data[key], dict) and 'name' in data[key]:
                return data[key]['name'].strip()

        return None

    def _get_nested_value(self, data: dict, path: str):
        """
        Get nested value from dict using dot notation
        """
        keys = path.split('.')
        current = data

        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None

        return current

    def _extract_from_css_selectors(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract using updated CSS selectors
        """
        # Updated selectors for 2024/2025
        selectors = [
            # New LinkedIn job page selectors
            '[data-test-id="job-details-header-company-name"]',
            '[data-test-id="company-name"]',
            '.job-details-jobs-unified-top-card__company-name a',
            '.jobs-unified-top-card__company-name a',
            '.jobs-unified-top-card__company-name',
            '.job-details__company-link',
            '.jobs-company-name',

            # Alternative selectors
            '[data-tracking-control-name="public_jobs_topcard-org-name"]',
            '[data-tracking-control-name="public_jobs_topcard_org_name"]',
            '.topcard__org-name-redirect',
            '.job-details-jobs-unified-top-card__primary-description-container a',

            # Generic fallbacks
            '[class*="company-name"]',
            '[class*="employer-name"]',
            '[data-test*="company"]',
            '[data-testid*="company"]'
        ]

        for selector in selectors:
            element = soup.select_one(selector)
            if element:
                text = element.get_text(strip=True)
                if text and len(text) > 1 and len(text) < 100:
                    return text

        return None

    def _extract_from_meta_tags(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract company name from meta tags and page title
        """
        # Check meta tags
        meta_selectors = [
            'meta[property="og:site_name"]',
            'meta[name="author"]',
            'meta[property="article:author"]',
            'meta[name="company"]',
            'meta[property="og:title"]'
        ]

        for selector in meta_selectors:
            meta = soup.select_one(selector)
            if meta:
                content = meta.get('content', '')
                if content and len(content) > 1 and len(content) < 100:
                    # Clean up common suffixes
                    content = re.sub(r'\s*\|\s*LinkedIn.*$', '', content)
                    content = re.sub(r'\s*-\s*LinkedIn.*$', '', content)
                    if content.strip():
                        return content.strip()

        # Check page title
        title = soup.find('title')
        if title:
            title_text = title.get_text(strip=True)
            # LinkedIn job titles often follow pattern: "Job Title - Company Name | LinkedIn"
            match = re.search(r'-\s*([^|]+?)\s*\|\s*LinkedIn', title_text)
            if match:
                company = match.group(1).strip()
                if company and len(company) > 1:
                    return company

        return None

    def _extract_from_text_patterns(self, soup: BeautifulSoup) -> Optional[str]:
        """
        Extract company name using text pattern matching
        """
        # Look for common text patterns
        patterns = [
            r'(?i)company:\s*([^\n\r,]+)',
            r'(?i)employer:\s*([^\n\r,]+)',
            r'(?i)organization:\s*([^\n\r,]+)',
            r'(?i)hiring\s+company:\s*([^\n\r,]+)'
        ]

        page_text = soup.get_text()

        for pattern in patterns:
            matches = re.findall(pattern, page_text)
            for match in matches:
                match = match.strip()
                if match and len(match) > 1 and len(match) < 100:
                    # Clean up common words
                    if not any(word in match.lower() for word in ['linkedin', 'job', 'career', 'position']):
                        return match

        return None
