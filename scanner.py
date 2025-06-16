from typing import Optional, Dict, Any, List
import spacy
import re
from fastapi import HTTPException
from keybert import KeyBERT
from schema import JobAnalysisResponse, Skill
import logging
import sys
from sentence_transformers import SentenceTransformer

# os.environ["HF_HUB_TOKEN"] = os.environ.get("HF_HUB_TOKEN")

logging.basicConfig(
    level=logging.DEBUG,  # or INFO if you want less noise
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)  # ensures logs show up in console
    ]
)

# Load models (do this once at startup)
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    print("Please install spacy English model: python -m spacy download en_core_web_sm")
    raise

local_model = SentenceTransformer("all-MiniLM-L6-v2")
kw_model = KeyBERT(model=local_model)


class JobAnalyzer:
    def __init__(self):
        self.common_job_titles = {
            'software', 'engineer', 'developer', 'programmer', 'architect',
            'manager', 'lead', 'senior', 'junior', 'analyst', 'scientist',
            'designer', 'consultant', 'specialist', 'coordinator', 'director'
        }

        self.experience_patterns = [
            r'(\d+)[\+\-\s]*(?:to|\-|–)?\s*(\d+)?\s*(?:years?|yrs?)\s+(?:of\s+)?experience',
            r'(\d+)[\+\s]*(?:years?|yrs?)\s+(?:of\s+)?(?:experience|exp)',
            r'minimum\s+(\d+)\s+(?:years?|yrs?)',
            r'at\s+least\s+(\d+)\s+(?:years?|yrs?)',
        ]

        self.skill_keywords = {
            'programming': ['python', 'java', 'javascript', 'c++', 'c#', 'ruby', 'go', 'rust'],
            'web': ['html', 'css', 'react', 'angular', 'vue', 'node.js', 'express'],
            'database': ['sql', 'mysql', 'postgresql', 'mongodb', 'redis'],
            'cloud': ['aws', 'azure', 'gcp', 'docker', 'kubernetes'],
            'tools': ['git', 'jenkins', 'jira', 'confluence']
        }

    def extract_company_name(self, text: str) -> Optional[str]:
        """Extract company name using spaCy NER and patterns"""
        doc = nlp(text)

        # Look for ORG entities in the first few sentences
        first_part = ' '.join(text.split()[:100])  # First 100 words
        first_doc = nlp(first_part)

        companies = []
        for ent in first_doc.ents:
            if ent.label_ in ['ORG'] and len(ent.text.split()) <= 4:
                companies.append(ent.text)

        # Additional patterns for company names
        company_patterns = [
            r'(?:at|@)\s+([A-Z][a-zA-Z\s&]+(?:Inc|LLC|Corp|Ltd|Company)?)',
            r'([A-Z][a-zA-Z\s&]+(?:Inc|LLC|Corp|Ltd|Company))\s+is\s+(?:hiring|looking)',
        ]

        for pattern in company_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            companies.extend(matches)

        return companies[0].strip() if companies else None

    def extract_job_title(self, text: str) -> Optional[str]:
        """Extract job title using patterns and NER"""
        # Common job title patterns
        title_patterns = [
            r'(?:position|role|job)\s*:?\s*([A-Z][a-zA-Z\s\-/]+(?:Engineer|Developer|Manager|Analyst|Designer|Lead|Director))',
            r'(?:hiring|seeking)\s+(?:a|an)?\s*([A-Z][a-zA-Z\s\-/]+(?:Engineer|Developer|Manager|Analyst|Designer|Lead|Director))',
            r'^([A-Z][a-zA-Z\s\-/]+(?:Engineer|Developer|Manager|Analyst|Designer|Lead|Director))',
        ]

        for pattern in title_patterns:
            match = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
            if match:
                title = match.group(1).strip()
                if any(keyword in title.lower() for keyword in self.common_job_titles):
                    return title

        # Fallback: look for common job title words in first line
        first_line = text.split('\n')[0] if '\n' in text else text.split('.')[0]
        words = first_line.lower().split()
        if any(title_word in words for title_word in self.common_job_titles):
            return first_line.strip()

        return None

    def extract_skills_and_experience(self, text: str) -> List[Skill]:
        """Extract skills with associated experience requirements"""
        skills = []

        # Use KeyBERT to extract relevant keywords
        keywords = kw_model.extract_keywords(text, keyphrase_ngram_range=(1, 3), stop_words='english', top_n=20)

        # Filter keywords that match known skills
        all_skills = []
        for category, skill_list in self.skill_keywords.items():
            all_skills.extend(skill_list)

        relevant_skills = []
        for keyword, score in keywords:
            if any(skill.lower() in keyword.lower() for skill in all_skills):
                relevant_skills.append(keyword)

        # Extract experience for each skill
        for skill in relevant_skills:
            experience = self.extract_experience_for_skill(text, skill)
            is_required = self.is_skill_required(text, skill)

            skills.append(Skill(
                name=skill,
                years_experience=experience,
                is_required=is_required
            ))

        return skills

    def extract_experience_for_skill(self, text: str, skill: str) -> Optional[str]:
        """Extract experience requirement for a specific skill"""
        # Look for experience mentions near the skill
        skill_context = self.get_context_around_skill(text, skill)

        for pattern in self.experience_patterns:
            match = re.search(pattern, skill_context, re.IGNORECASE)
            if match:
                if match.group(2):  # Range like "3-5 years"
                    return f"{match.group(1)}-{match.group(2)} years"
                else:  # Single number like "3+ years"
                    return f"{match.group(1)}+ years"

        return None

    def get_context_around_skill(self, text: str, skill: str, window: int = 50) -> str:
        """Get text context around a skill mention"""
        words = text.split()
        skill_indices = []

        for i, word in enumerate(words):
            if skill.lower() in word.lower():
                skill_indices.append(i)

        if not skill_indices:
            return ""

        # Get context around first mention
        idx = skill_indices[0]
        start = max(0, idx - window)
        end = min(len(words), idx + window)

        return ' '.join(words[start:end])

    def is_skill_required(self, text: str, skill: str) -> bool:
        """Determine if a skill is required or preferred"""
        skill_context = self.get_context_around_skill(text, skill)

        required_indicators = ['required', 'must have', 'essential', 'mandatory']
        preferred_indicators = ['preferred', 'nice to have', 'bonus', 'plus']

        context_lower = skill_context.lower()

        for indicator in required_indicators:
            if indicator in context_lower:
                return True

        return False

    def extract_additional_details(self, text: str, url: Optional[str] = None) -> Dict[str, Any]:
        """Extract additional job posting details"""
        details = {}

        # Salary extraction
        salary_pattern = r'\$[\d,]+(?:\s*-\s*\$?[\d,]+)?(?:\s*(?:per\s+)?(?:year|annually|k|K))?'
        salary_matches = re.findall(salary_pattern, text)
        if salary_matches:
            details['salary_range'] = salary_matches[0]

        # Remote work detection
        remote_keywords = ['remote', 'work from home', 'distributed', 'telecommute']
        details['remote_work'] = any(keyword in text.lower() for keyword in remote_keywords)

        # Company size indicators
        size_patterns = [
            r'(\d+[\+\-\s]*(?:to|\-)?\s*\d*)\s+employees',
            r'(?:startup|small|medium|large|enterprise)\s+(?:company|organization)'
        ]

        for pattern in size_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                details['company_size'] = match.group(0)
                break

        # Education requirements
        education_keywords = ['bachelor', 'master', 'phd', 'degree', 'university', 'college']
        details['education_required'] = any(keyword in text.lower() for keyword in education_keywords)

        if url:
            details['source_url'] = url

        return details

    def calculate_confidence_scores(self, result: Dict[str, Any]) -> Dict[str, float]:
        """Calculate confidence scores for extracted information"""
        scores = {'company_name': 0.8 if result.get('company_name') else 0.0,
                  'job_title': 0.9 if result.get('job_title') else 0.0}

        # Skills confidence based on number found
        num_skills = len(result.get('skills', []))
        scores['skills'] = min(0.9, num_skills * 0.1)

        # Keywords confidence
        num_keywords = len(result.get('keywords', []))
        scores['keywords'] = min(0.9, num_keywords * 0.05)

        return scores

    def analyze(self, content: str, url: Optional[str] = None, title: Optional[str] = None,
                company_guess: Optional[str] = None) -> JobAnalysisResponse:
        """Main analysis method"""
        try:
            # Use provided title as fallback if extraction fails
            job_title = self.extract_job_title(content)
            if not job_title and title:
                job_title = title

            # Use provided company guess as fallback if extraction fails
            company_name = self.extract_company_name(content)
            if not company_name and company_guess:
                company_name = company_guess

            skills = self.extract_skills_and_experience(content)

            # Extract keywords using KeyBERT
            keywords_raw = kw_model.extract_keywords(content, keyphrase_ngram_range=(1, 2), stop_words='english', top_n=15)
            keywords = [kw[0] for kw in keywords_raw]

            # Extract experience level
            experience_level = None
            exp_patterns = [
                r'(entry.level|junior|senior|lead|principal|staff)',
                r'(\d+)[\+\s]*(?:years?|yrs?)\s+(?:of\s+)?(?:total\s+)?experience'
            ]

            for pattern in exp_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    experience_level = match.group(1)
                    break

            additional_details = self.extract_additional_details(content, url)

            # Add browser extension provided data to additional details
            if title:
                additional_details['page_title'] = title
            if company_guess:
                additional_details['company_guess'] = company_guess

            # Create result dict for confidence calculation
            result_dict = {
                'company_name': company_name,
                'job_title': job_title,
                'skills': skills,
                'keywords': keywords
            }

            confidence_scores = self.calculate_confidence_scores(result_dict)

            return JobAnalysisResponse(
                success=True,
                company_name=company_name,
                job_title=job_title,
                companyUrl=None,
                keywords=keywords,
                skills=skills,
                experience_level=experience_level,
                additional_details=additional_details,
                confidence_scores=confidence_scores
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")