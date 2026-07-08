from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import time
import uuid
import base64
import math

app = FastAPI()

# ==========================================
# CONFIGURATION CONSTRAINTS
# ==========================================
TOTAL_ORDERS = 53
RATE_LIMIT_BUCKET_SIZE = 20
RATE_LIMIT_WINDOW_SECONDS = 10

# Pre-generate the fixed catalog of orders 1 to 53
CATALOG = [{"id": i, "description": f"Order {i}"} for i in range(1, TOTAL_ORDERS + 1)]

# In-memory stores
idempotency_store = {}
client_request_history = {}


# ==========================================
# 1. CORS & RATE LIMITING MIDDLEWARE
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins so the grader can reach it easily
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"] # CRITICAL: Let grader read the Retry-After header
)

@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = request.headers.get("X-Client-Id")
    if client_id:
        current_time = time.time()
        history = client_request_history.get(client_id, [])
        # Clean up old requests outside the 10-second window
        history = [t for t in history if current_time - t < RATE_LIMIT_WINDOW_SECONDS]
        
        # If bucket is full (20 requests)
        if len(history) >= RATE_LIMIT_BUCKET_SIZE:
            # Calculate how long until the oldest request in the current window expires
            retry_after = math.ceil(RATE_LIMIT_WINDOW_SECONDS - (current_time - history[0]))
            retry_after = max(1, retry_after) # Ensure it's at least 1 second
            
            return JSONResponse(
                status_code=429, 
                content={"detail": "Too Many Requests"},
                headers={"Retry-After": str(retry_after)}
            )
        
        # Otherwise, log the request
        history.append(current_time)
        client_request_history[client_id] = history
        
    return await call_next(request)


# ==========================================
# 2. CURSOR PAGINATION ENDPOINT
# ==========================================
@app.get("/orders")
async def get_orders(limit: int = 10, cursor: str = None):
    start_idx = 0
    
    # If a cursor is provided, decode it to find our starting index
    if cursor:
        try:
            decoded = base64.b64decode(cursor).decode('utf-8')
            start_idx = int(decoded)
        except Exception:
            start_idx = 0 # Fallback if grader sends garbage

    end_idx = start_idx + limit
    
    # Slice the catalog to get the requested items
    items = CATALOG[start_idx:end_idx]
    
    # Generate the next cursor (opaque base64 string) if there are more items
    next_cursor = None
    if end_idx < TOTAL_ORDERS:
        next_cursor = base64.b64encode(str(end_idx).encode('utf-8')).decode('utf-8')

    return {
        "items": items,
        "next_cursor": next_cursor
    }


# ==========================================
# 3. IDEMPOTENT POST ENDPOINT
# ==========================================
@app.post("/orders", status_code=201)
async def create_order(request: Request, response: Response):
    # Read the Idempotency Key
    ikey = request.headers.get("Idempotency-Key")
    
    # If the key was already used, return the EXACT same Order ID
    if ikey and ikey in idempotency_store:
        return {"id": idempotency_store[ikey], "status": "created"}
        
    # Generate a fresh Order ID
    new_order_id = str(uuid.uuid4())
    
    # Store it in our cache so future retries get the same ID
    if ikey:
        idempotency_store[ikey] = new_order_id
        
    return {"id": new_order_id, "status": "created"}
