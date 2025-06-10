from typing import Optional
from known_sites.base_class import JobSiteParser
from known_sites.linkedin import LinkedInParser
from known_sites.indeed import IndeedParser

class JobParserFactory:
    """Factory class to get the appropriate parser for a URL"""

    def __init__(self):
        self.parsers = [
            LinkedInParser(),
            IndeedParser(),
            # Add more parsers here
        ]

    def get_parser(self, url: Optional[str]) -> Optional[JobSiteParser]:
        """Get the appropriate parser for the given URL"""
        if not url:
            return None

        for parser in self.parsers:
            if parser.can_parse(url):
                return parser

        return None

    def can_parse_format(self, url: Optional[str]) -> bool:
        """Check if we have a parser for this URL"""
        return self.get_parser(url) is not None