# Reels API

All routes use the `/api/v1` prefix and require a bearer token for the indicated role.

## Mobile feature mapping

| Mobile behavior | API |
| --- | --- |
| Category chips | `GET /customer/reels/categories` |
| Paginated category feed | `GET /customer/reels?category=Food&limit=20&offset=0` |
| Saved ads screen | `GET /customer/reels?saved_only=true` |
| Like / unlike | `PUT` / `DELETE /customer/reels/{reel_id}/like` |
| Save / unsave | `PUT` / `DELETE /customer/reels/{reel_id}/save` |
| Unique view and completion | `POST /customer/reels/{reel_id}/view` |
| Share analytics | `POST /customer/reels/{reel_id}/share` |
| Call or Shop Now analytics | `POST /customer/reels/{reel_id}/cta-click` |

The feed includes image/video URLs, optional video poster, category, engagement counts,
the current user's like/save state, CTA metadata, and advertiser shop name, logo, phone,
and WhatsApp number. Play/pause and mute/unmute remain device-only player controls.

## Shopkeeper publishing flow

1. Request an image or video upload with `POST /shopkeeper/reels/media/presign`.
2. Upload the file to the returned presigned URL.
3. Confirm it with `POST /shopkeeper/reels/media/{asset_id}/complete`.
4. Create the draft with `POST /shopkeeper/reels`.
5. Publish it with `POST /shopkeeper/reels/{reel_id}/publish`.

Shopkeepers can list, read, edit, pause, archive, and view analytics for their own reels.
Only reels belonging to active shops and inside their optional start/end window appear in
the customer feed. Media assets and linked products are ownership checked.

Image uploads default to a 10 MB limit. Video uploads default to 100 MB and can be
configured with `MEDIA_MAX_VIDEO_UPLOAD_BYTES`.

## Deployment

Apply database revision `010` before starting this API version:

```bash
uv run alembic upgrade head
```
