from pydantic import BaseModel
from typing import List, Optional, Dict, Any

# Request/Response models
class JobPostingRequest(BaseModel):
    content: str
    url: Optional[str] = None
    rawHTML : Optional[str] = None
    title: Optional[str] = None
    companyGuess: Optional[str] = None


class Skill(BaseModel):
    name: str
    years_experience: Optional[str] = None
    is_required: bool = False

class JobAnalysisResponse(BaseModel):
    success: bool
    company_name: Optional[str]
    companyUrl: Optional[str]
    job_title: Optional[str]
    keywords: List[str]
    skills: List[Skill]
    experience_level: Optional[str]
    additional_details: Dict[str, Any]
    confidence_scores: Dict[str, float]