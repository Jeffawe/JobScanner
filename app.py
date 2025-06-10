from fastapi import FastAPI, HTTPException, Request
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import redis.asyncio as redis
import json
import hashlib
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from known_sites.base_parsers import JobParserFactory
from scanner import JobAnalyzer
from schema import JobAnalysisResponse, JobPostingRequest
import logging
import sys
import os
import time
from typing import Optional
from site_searcher.site_finder import EnhancedCareerPageFinder

load_dotenv()

logging.basicConfig(
    level=logging.INFO,  # Use INFO for production
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Environment variables
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# Rate limiting configuration
limiter = Limiter(key_func=get_remote_address)

# Global variables for shared resources
redis_client: Optional[redis.Redis] = None
analyzer: Optional[JobAnalyzer] = None
parser_factory: Optional[JobParserFactory] = None
finder: Optional[EnhancedCareerPageFinder] = None

async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Custom handler for rate limit exceeded errors"""
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": f"Rate limit exceeded: {exc.detail}",
            "retry_after": getattr(exc, 'retry_after', None)
        }
    )

@asynccontextmanager
async def lifespan(local_app: FastAPI):
    """Manage application startup and shutdown"""
    global redis_client, analyzer, parser_factory, finder

    logger.info("Starting up Job Posting Analyzer API...")

    # Initialize Redis connection
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        redis_client = None

    # Initialize components
    analyzer = JobAnalyzer()
    parser_factory = JobParserFactory()
    finder = EnhancedCareerPageFinder(GOOGLE_API_KEY, SEARCH_ENGINE_ID)

    logger.info("Application startup complete")

    yield

    # Cleanup
    logger.info("Shutting down...")
    if redis_client:
        await redis_client.close()
    logger.info("Shutdown complete")


# Initialize FastAPI app
app = FastAPI(
    title="Job Posting Analyzer",
    version="1.0.0",
    description="Production-ready job posting analysis API with caching and rate limiting",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware, # type: ignore
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8080",
        "chrome-extension://your-extension-id-here"
    ] if ENVIRONMENT == "development" else ["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Add GZip compression middleware
app.add_middleware(GZipMiddleware, minimum_size=1000) # type: ignore

# Add security middleware for production
if ENVIRONMENT == "production":
    app.add_middleware(
        TrustedHostMiddleware, # type: ignore
        allowed_hosts=ALLOWED_HOSTS
    )

# Add rate limiting middleware (should be close to the app)
app.state.limiter = limiter  # type: ignore[attr-defined]
app.add_exception_handler(RateLimitExceeded, custom_rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)  # type: ignore

# Custom middleware for request timing and logging
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)

    # Log request details for monitoring
    logger.info(
        f"Request: {request.method} {request.url.path} "
        f"- Status: {response.status_code} "
        f"- Time: {process_time:.3f}s"
    )

    return response


# Cache helper functions
def generate_cache_key(content: str, url: str) -> str:
    """Generate a cache key from content and URL"""
    combined = f"{url}:{content}"
    return f"job_analysis:{hashlib.md5(combined.encode()).hexdigest()}"


async def get_from_cache(cache_key: str) -> Optional[dict]:
    """Get analysis result from cache"""
    if not redis_client:
        return None

    try:
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            logger.info(f"Cache hit for key: {cache_key[:16]}...")
            return json.loads(cached_data)
    except Exception as e:
        logger.error(f"Cache read error: {e}")

    return None


async def set_cache(cache_key: str, data: dict, ttl: int = 3600) -> None:
    """Store analysis result in cache"""
    if not redis_client:
        return

    try:
        await redis_client.setex(
            cache_key,
            ttl,
            json.dumps(data, default=str)
        )
        logger.info(f"Cached result for key: {cache_key[:16]}...")
    except Exception as e:
        logger.error(f"Cache write error: {e}")


# Dependency to get Redis client
async def get_redis() -> Optional[redis.Redis]:
    return redis_client


@app.post("/analyze", response_model=JobAnalysisResponse)
@limiter.limit("30/minute")  # Rate limit: 30 requests per minute per IP
async def analyze_job_posting(
        request: Request,
        job_request: JobPostingRequest
):
    """Analyze job posting content and extract key information"""
    try:
        if not job_request.content.strip():
            raise HTTPException(status_code=400, detail="Content cannot be empty")

        # Generate cache key
        cache_key = generate_cache_key(job_request.content, job_request.url or "")

        # Try to get from cache first
        cached_result = await get_from_cache(cache_key)
        if cached_result:
            return JobAnalysisResponse(**cached_result)

        # Proceed with analysis
        parser = parser_factory.get_parser(job_request.url)
        result = None

        if parser and job_request.rawHTML:
            logger.info(f"Using format-specific parser for URL: {job_request.url}")
            result = parser.parse(job_request.rawHTML, job_request.url)
        else:
            logger.info(f"Using NLP analyzer for URL: {job_request.url}")
            result = analyzer.analyze(job_request.content, job_request.url)

        if not result:
            raise HTTPException(status_code=500, detail="Analysis failed")

        # Enhance result with missing information
        if not result.job_title and job_request.title:
            result.job_title = job_request.title
        if not result.company_name and job_request.companyGuess:
            result.company_name = job_request.companyGuess

        # Find company career page if missing
        if not result.companyUrl and result.company_name:
            try:
                career_page_result = finder.find_career_page(result.company_name)
                if career_page_result:
                    result.companyUrl = career_page_result['career_url']
            except Exception as e:
                logger.warning(f"Failed to find career page: {e}")

        # Convert result to dict for caching
        result_dict = result.model_dump() if hasattr(result, 'dict') else result.__dict__

        # Cache the result (1 hour TTL)
        await set_cache(cache_key, result_dict, ttl=3600)

        logger.info(f"Analysis completed for URL: {job_request.url}")
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis failed: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.post("/test", response_model=JobAnalysisResponse)
@limiter.limit("10/minute")
async def test_job_posting(request: JobPostingRequest):
    """Analyze job posting content and extract key information"""
    try:
        if not request.content.strip():
            raise HTTPException(status_code=400, detail="Content cannot be empty")

        logging.info(request)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.post("/check-parser-support")
async def check_parser_support(request: dict):
    """Check if a URL is supported by format-specific parsers"""
    url = request.get("url")
    is_supported = parser_factory.can_parse_format(url)
    parser_type = "format-specific" if is_supported else "nlp-analysis"

    return {
        "url": url,
        "supported": is_supported,
        "parser_type": parser_type
    }


@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint"""
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "environment": ENVIRONMENT,
        "services": {}
    }

    # Check Redis connection
    if redis_client:
        try:
            await redis_client.ping()
            health_status["services"]["redis"] = "connected"
        except Exception as e:
            health_status["services"]["redis"] = f"error: {str(e)}"
            health_status["status"] = "degraded"
    else:
        health_status["services"]["redis"] = "not configured"

    # Check API keys
    health_status["services"]["google_api"] = "configured" if GOOGLE_API_KEY else "missing"
    health_status["services"]["search_engine"] = "configured" if SEARCH_ENGINE_ID else "missing"

    return health_status


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Job Posting Analyzer API",
        "version": "1.0.0",
        "endpoints": {
            "analyze": "/analyze (POST)",
            "health": "/health (GET)",
            "docs": "/docs (GET)"
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)