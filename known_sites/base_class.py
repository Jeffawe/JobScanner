from typing import Optional
from schema import JobAnalysisResponse

class JobSiteParser:
    """Base class for job site parsers"""

    def can_parse(self, url: str) -> bool:
        """Check if this parser can handle the given URL"""
        raise NotImplementedError

    def parse(self, content: str, url: Optional[str] = None) -> JobAnalysisResponse:
        """Parse job posting content into structured data"""
        raise NotImplementedError