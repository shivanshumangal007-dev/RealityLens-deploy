from fastapi import Request
from fastapi.responses import JSONResponse
import time
from .Redis_Otp import redis_otp_db

async def global_rate_limit_middleware(request: Request, call_next):
    # Paths that should be excluded from rate limiting entirely
    excluded_paths = ["/docs", "/openapi.json", "/redoc", "/health_check", "/update_check"]
    if request.url.path in excluded_paths:
        return await call_next(request)
        
    client_ip = request.client.host if request.client else "127.0.0.1"
    
    # Use the current minute as part of the cache key
    current_minute = int(time.time() // 60)
    
    # ---------------------------------------------------------
    # 1. Global Rate Limit (100 requests per minute per IP)
    # ---------------------------------------------------------
    global_key = f"rl:global:{client_ip}:{current_minute}"
    try:
        global_count = await redis_otp_db.incr(global_key)
        if global_count == 1:
            await redis_otp_db.expire(global_key, 60)
            
        if global_count > 100:
            return JSONResponse(
                status_code=429, 
                content={"detail": "Too Many Requests. Please try again later."}
            )
    except Exception as e:
        # If Redis fails, log it and allow request to pass (fail open)
        print(f"Redis rate limit error (global): {e}")

    # ---------------------------------------------------------
    # 2. Strict OTP Route Limit (5 requests per minute per IP)
    # ---------------------------------------------------------
    otp_routes = ["/register", "/login", "/change-user-details", "/delete-account"]
    if any(request.url.path.endswith(route) for route in otp_routes):
        otp_key = f"rl:otp:{client_ip}:{current_minute}"
        try:
            otp_count = await redis_otp_db.incr(otp_key)
            if otp_count == 1:
                await redis_otp_db.expire(otp_key, 60)
                
            if otp_count > 5:
                return JSONResponse(
                    status_code=429, 
                    content={"detail": "Too many OTP requests from this IP. Please wait."}
                )
        except Exception as e:
            print(f"Redis rate limit error (otp): {e}")

    # Process the request
    response = await call_next(request)
    return response
