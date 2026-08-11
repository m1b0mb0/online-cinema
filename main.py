from fastapi import FastAPI

from src.routes import (
    accounts_router,
    admin_router,
    cart_router,
    catalog_router,
    comments_router,
    favorites_router,
    movies_router,
    orders_router,
    payments_router,
    ratings_router,
    reactions_router,
)

app = FastAPI(
    title="Online Cinema API",
    description="API for managing movies, users, and orders",
)


app.include_router(accounts_router, prefix="/accounts", tags=["Accounts"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])
app.include_router(cart_router, prefix="/theater", tags=["Cart"])
app.include_router(catalog_router, prefix="/theater", tags=["Catalog"])
app.include_router(comments_router, prefix="/theater", tags=["Comments"])
app.include_router(movies_router, prefix="/theater", tags=["Theater"])
app.include_router(orders_router, prefix="/theater", tags=["Orders"])
app.include_router(payments_router, prefix="/theater", tags=["Payments"])
app.include_router(favorites_router, prefix="/theater", tags=["Favorites"])
app.include_router(reactions_router, prefix="/theater", tags=["Reactions"])
app.include_router(ratings_router, prefix="/theater", tags=["Ratings"])
