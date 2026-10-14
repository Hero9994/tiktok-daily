# Approved sports graphics — 2026-10-14

Adopts the user-provided black/gold stadium, trophy and bottom-left football reference. Background artwork has no baked-in fixtures or team marks. Team crests, Arabic names, Germany/Makkah times, fixture date and page count are rendered from verified provider data. Six matches per page; all pages remain in the existing 20-second video with the approved sports music.

The reusable background is committed; no additional daily image-generation API charge. Rendering does not copy the reference screenshot’s fixture facts.

Unsubmitted image_ready sports entries re-render on template version changes, using the current configured background. Their video fingerprint then forces re-encoding. Accepted/sent posts retain the existing idempotent handling.

Validation: 68 local tests passed, including template migration with unchanged fixtures and no paid image request. Six preview pages rendered from the previously verified 36-fixture snapshot for 2026-10-15. This snapshot is for visual review; live publication refreshes fixtures before submission.
