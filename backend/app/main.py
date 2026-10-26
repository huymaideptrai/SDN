from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio
from app.core.config import settings
from app.models.database import engine, Base
from app.models import migrations
from app.routers import admin, auth, devices, sdn
from app.services.ryu_client import RyuError, ryu_client
from app.tasks.sync_worker import sync_flow_state


migrations.upgrade(engine)
Base.metadata.create_all(bind=engine)
@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_task = asyncio.create_task(sync_flow_state())

    yield
    sync_task.cancel()
    await ryu_client.aclose()

app = FastAPI(
    title="SDN Enterprise Controller API",
    description="Backend API kết nối Frontend React với Ryu Controller",
    version="1.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RyuError)
async def ryu_error_handler(request: Request, exc: RyuError):
    return JSONResponse(status_code=exc.status_code, content={"status": "error", "detail": exc.message})

app.include_router(auth.router)
app.include_router(sdn.router)
app.include_router(admin.router)
app.include_router(devices.router)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "SDN Backend is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
