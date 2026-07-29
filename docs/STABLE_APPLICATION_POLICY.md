# Stable application policy

The candidate catalogue records application/category, maintenance owner, source, license, signature, Wayland, accessibility, permissions/privacy, architecture, update path, and inclusion reason. Native system applications follow the image-maintenance path; per-user Flatpaks follow their signed remote/runtime lifecycle and portal policy. Application updates are not coupled to a full OS image unless image ownership requires it.

Defaults stay minimal: browser, terminal, files, settings, and essential recovery/diagnostics, with editor/PDF/image/media/archive tools only after the catalogue passes. `operations/data/application-catalogue.json` is unqualified; the Bunny placeholder is ineligible for stable inclusion.
