from urllib.parse import quote

from app.core.config import settings


PRODUCT_BUCKET = "product-images"
CATEGORY_BUCKET = "category-images"
SITE_BUCKET = "site-assets"


def public_storage_url(bucket: str, path: str) -> str:
    encoded_path = "/".join(
        quote(part, safe="")
        for part in path.split("/")
        if part
    )

    return (
        f"{settings.supabase_url}/storage/v1/object/public/"
        f"{bucket}/{encoded_path}"
    )
