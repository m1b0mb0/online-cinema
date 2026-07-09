from fastapi import FastAPI

from src.routes import accounts_router

app = FastAPI(
    title="Online Cinema API",
    description="API for managing movies, users, and orders",
)


app.include_router(accounts_router, prefix=f"/accounts")
