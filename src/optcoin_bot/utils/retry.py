import asyncio
import logging
from functools import wraps

logger = logging.getLogger(__name__)

def async_retry(max_attempts: int = 1, delay: float = 0.5, catch_exceptions=Exception):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except catch_exceptions as e:
                    logger.warning(
                        f"Attempt {attempt}/{max_attempts} failed for {func.__name__}: {e}"
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(delay)
                    else:
                        raise
        return wrapper
    return decorator