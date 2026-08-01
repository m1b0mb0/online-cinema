from fastapi import FastAPI

from src.routes import (
    accounts_router,
    admin_router,
    catalog_router,
    comments_router,
    favorites_router,
    movies_router,
    ratings_router,
    reactions_router,
)

app = FastAPI(
    title="Online Cinema API",
    description="API for managing movies, users, and orders",
)


app.include_router(accounts_router, prefix=f"/accounts", tags=["Accounts"])
app.include_router(admin_router, prefix=f"/admin", tags=["Admin"])
app.include_router(catalog_router, prefix=f"/theater", tags=["Catalog"])
app.include_router(comments_router, prefix=f"/theater", tags=["Comments"])
app.include_router(movies_router, prefix=f"/theater", tags=["Theater"])
app.include_router(favorites_router, prefix=f"/theater", tags=["Favorites"])
app.include_router(reactions_router, prefix=f"/theater", tags=["Reactions"])
app.include_router(ratings_router, prefix=f"/theater", tags=["Ratings"])
