# Open Items

## Post-MVP API cleanup

- [ ] Replace mutable page-index image identity with stable page IDs before finalizing the API. The current filename-based cache key is reliable and safe for the MVP, but the final image endpoint should identify pages by an opaque, stable page ID while keeping `pageIndex` only for presentation order. A target shape is `GET /api/v1/galleries/{gallery_id}/pages/{page_id}/image?v={modified_ns}`.
