from pathlib import Path

from scripts.seed_demo_data import (
    CATEGORIES,
    CITY_SHOP_CATEGORY_SLUGS,
    DEMO_SIZE,
    OFFER_PROMOTIONS,
    PRODUCTS,
    REELS,
    SHOP_CATEGORY_PORTFOLIOS,
    SHOPS,
)


def test_demo_collections_meet_client_demo_size():
    assert DEMO_SIZE == 20
    assert len(CATEGORIES) >= 20
    assert len(SHOPS) >= 20
    assert len(PRODUCTS) >= 20
    assert len({item[0] for item in CATEGORIES}) == len(CATEGORIES)
    assert len({item[0] for item in SHOPS}) == len(SHOPS)
    assert len({item[0] for item in PRODUCTS}) == len(PRODUCTS)


def test_city_shop_categories_match_the_customer_design():
    assert CITY_SHOP_CATEGORY_SLUGS == {
        "fresh-vegetables",
        "fruits",
        "dairy",
        "rice-atta-dals",
        "masalas-dry-fruits",
        "edible-oils-ghee",
        "munchies",
        "chocolates-ice-cream",
        "cold-drinks-juices",
        "biscuits-cakes",
        "instant-frozen-food",
        "meat-seafood",
    }


def test_every_city_category_has_relevant_demo_shops_and_products():
    product_categories = {item[2] for item in PRODUCTS}
    for category_slug in CITY_SHOP_CATEGORY_SLUGS:
        assert category_slug in product_categories
        matching_shops = [
            shop_key
            for shop_key, categories in SHOP_CATEGORY_PORTFOLIOS.items()
            if category_slug in categories
        ]
        assert len(matching_shops) >= 3

    assert "dairy" not in SHOP_CATEGORY_PORTFOLIOS["tech-corner"]
    assert "dairy" not in SHOP_CATEGORY_PORTFOLIOS["smart-life"]
    assert "dairy" not in SHOP_CATEGORY_PORTFOLIOS["gadget-hub"]


def test_all_seeded_catalog_images_are_project_local():
    static_dir = Path(__file__).resolve().parents[1] / "static" / "demo"
    filenames = {item[2] for item in CATEGORIES}
    filenames.update(item[4] for item in SHOPS)
    filenames.update(item[4] for item in PRODUCTS)
    filenames.update({"profile-aarav.webp", "reward-pastry.webp", "reward-scratch.webp"})
    filenames.update(item[3] for item in OFFER_PROMOTIONS)
    filenames.update(item[5] for item in REELS)
    filenames.update(item[6] for item in REELS)
    missing = sorted(filename for filename in filenames if not (static_dir / filename).is_file())
    assert missing == []


def test_demo_reels_cover_the_mobile_categories():
    assert {item[3] for item in REELS} == {"Daily Needs", "Food", "Fashion", "Beauty"}
    assert len({item[0] for item in REELS}) == len(REELS)
