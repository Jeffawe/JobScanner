from typing import List, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import re
from schema import JobAnalysisResponse, Skill
from known_sites.base_class import JobSiteParser

class IndeedParser(JobSiteParser):
    """Parser for Indeed job postings"""

    def can_parse(self, url: str) -> bool:
        if not url:
            return False
        domain = urlparse(url).netloc.lower()
        return 'indeed.com' in domain

    def parse(self, content: str, url: Optional[str] = None) -> JobAnalysisResponse:
        soup = BeautifulSoup(content, 'html.parser')

        # Extract job title
        job_title_element = soup.select_one('h1[data-testid="jobsearch-JobInfoHeader-title"]')
        job_title = job_title_element.get_text(strip=True) if job_title_element else None

        # Extract company name
        company_element = soup.select_one('[data-testid="inlineHeader-companyName"]')
        company_name = company_element.get_text(strip=True) if company_element else None

        # Extract job description for skills and keywords
        description_element = soup.select_one('#jobDescriptionText, .jobsearch-jobDescriptionText')
        description_text = description_element.get_text().lower() if description_element else ""

        # Extract skills (similar logic to LinkedIn)
        skills = self._extract_skills_from_text(description_text)

        # Extract experience level
        experience_level = self._extract_experience_from_text(description_text)

        # Extract keywords
        keywords = self._extract_keywords_from_text(description_text)

        # Additional details
        additional_details = {
            "location": self._extract_location(soup),
            "salary": self._extract_salary(soup),
            "employment_type": self._extract_employment_type_from_text(description_text)
        }

        return JobAnalysisResponse(
            success=True,
            company_name=company_name,
            companyUrl=None,
            job_title=job_title,
            keywords=keywords,
            skills=skills,
            experience_level=experience_level,
            additional_details=additional_details,
            confidence_scores={"parsing": 0.95}
        )

    def _extract_skills_from_text(self, text: str) -> List[Skill]:
        # Similar to LinkedIn parser but adapted for Indeed's format
        skills = []
        tech_skills = [
            'python', 'javascript', 'java', 'react', 'angular', 'vue', 'node.js',
            'sql', 'postgresql', 'mysql', 'mongodb', 'redis', 'docker', 'kubernetes',
            'aws', 'azure', 'gcp', 'git', 'jenkins', 'ci/cd', 'rest api', 'graphql'
        ]

        for skill in tech_skills:
            if skill in text:
                years_pattern = rf'(\d+)\+?\s*years?\s*(?:of\s*)?(?:experience\s*)?(?:with\s*|in\s*)?{re.escape(skill)}'
                years_match = re.search(years_pattern, text, re.IGNORECASE)
                years_exp = years_match.group(1) + "+ years" if years_match else None

                is_required = any(req_word in text for req_word in ['required', 'must have', 'essential'])

                skills.append(Skill(
                    name=skill.title(),
                    years_experience=years_exp,
                    is_required=is_required
                ))

        return skills

    def _extract_experience_from_text(self, text: str) -> Optional[str]:
        if any(word in text for word in ['senior', 'sr.', 'lead', 'principal']):
            return "Senior"
        elif any(word in text for word in ['junior', 'jr.', 'entry level', 'graduate']):
            return "Junior"
        elif any(word in text for word in ['mid-level', 'intermediate', '3-5 years']):
            return "Mid-Level"
        return "Not specified"

    def _extract_keywords_from_text(self, text: str) -> List[str]:
        common_keywords = [
            'remote', 'hybrid', 'full-time', 'part-time', 'contract',
            'startup', 'enterprise', 'agile', 'scrum', 'team lead'
        ]
        return [keyword for keyword in common_keywords if keyword.lower() in text]

    def _extract_location(self, soup: BeautifulSoup) -> Optional[str]:
        location_element = soup.select_one('[data-testid="job-location"]')
        return location_element.get_text(strip=True) if location_element else None

    def _extract_salary(self, soup: BeautifulSoup) -> Optional[str]:
        salary_element = soup.select_one('[data-testid="attribute_snippet_testid"]')
        return salary_element.get_text(strip=True) if salary_element else None

    def _extract_employment_type_from_text(self, text: str) -> Optional[str]:
        if 'full-time' in text:
            return "Full-time"
        elif 'part-time' in text:
            return "Part-time"
        elif 'contract' in text:
            return "Contract"
        elif 'internship' in text:
            return "Internship"
        return None