from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from app.models.database import engine, Base
from app.routers import auth, sdn
from app.tasks.sync_worker import poll_ryu_stats, sync_flow_state


Base.metadata.create_all(bind=engine)
@asynccontextmanager
async def lifespan(app: FastAPI):
    task1 = asyncio.create_task(poll_ryu_stats())
    task2 = asyncio.create_task(sync_flow_state())
    
    yield
    task1.cancel()
    task2.cancel()

app = FastAPI(
    title="SDN Enterprise Controller API",
    description="Backend API kết nối Frontend React với Ryu Controller",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, tags=["Authentication"])
app.include_router(sdn.router)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "SDN Backend is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)