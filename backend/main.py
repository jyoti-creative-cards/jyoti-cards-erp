from fastapi import FastAPI

from db.database import init_db
from backend.routes.catalog import router as catalog_router
from backend.routes.orders import router as orders_router
from backend.routes.webhooks import router as webhooks_router
from services.scheduler import start_scheduler

init_db()
start_scheduler()
app = FastAPI(title="Jyoti Cards ERP Backend")
app.include_router(catalog_router)
app.include_router(orders_router)
app.include_router(webhooks_router)


@app.get("/")
def health():
    return {"status": "ok", "service": "jyoti-cards-erp-backend"}
