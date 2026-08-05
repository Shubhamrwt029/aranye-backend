from app.main import app


def test_customer_figma_routes_are_documented():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/auth/customer/send-otp",
        "/api/v1/auth/customer/verify-otp",
        "/api/v1/auth/profile/complete",
        "/api/v1/auth/profile",
        "/api/v1/customer/categories",
        "/api/v1/customer/home",
        "/api/v1/customer/promotions",
        "/api/v1/customer/search/shops",
        "/api/v1/customer/shops/{shop_id}/storefront",
        "/api/v1/customer/products/{product_id}",
        "/api/v1/customer/favorites",
        "/api/v1/customer/addresses",
        "/api/v1/customer/addresses/{address_id}",
        "/api/v1/customer/cart",
        "/api/v1/customer/orders/{order_id}",
    }
    assert expected <= set(paths)
    assert {"put", "delete"} <= set(paths["/api/v1/customer/addresses/{address_id}"])
    shop_parameters = paths["/api/v1/customer/shops"]["get"]["parameters"]
    assert "category_id" in {parameter["name"] for parameter in shop_parameters}
    search_parameters = paths["/api/v1/customer/search/shops"]["get"]["parameters"]
    search_parameters_by_name = {parameter["name"]: parameter for parameter in search_parameters}
    assert {"q", "city", "limit", "offset"} <= set(search_parameters_by_name)
    assert search_parameters_by_name["q"]["required"] is True


def test_scratch_card_routes_are_documented():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/admin/scratch-cards",
        "/api/v1/admin/scratch-cards/{card_id}",
        "/api/v1/admin/scratch-cards/{card_id}/assign",
        "/api/v1/admin/scratch-cards/{card_id}/analytics",
        "/api/v1/admin/scratch-cards/{card_id}/assignments",
        "/api/v1/customer/scratch-cards",
        "/api/v1/customer/scratch-cards/{assignment_id}/view",
        "/api/v1/customer/scratch-cards/{assignment_id}/scratch",
        "/api/v1/shopkeeper/scratch-card-redemptions/preview",
        "/api/v1/shopkeeper/scratch-card-redemptions/redeem",
    }
    assert expected <= set(paths)
