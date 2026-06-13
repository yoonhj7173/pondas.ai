# Craft — Design Handoff

This package is split into two independently-buildable parts. Build them separately.

| Folder | What it is | Build target |
|---|---|---|
| `product/` | The Craft app — onboarding + office map + all panels/modals/overlays | PixiJS world + React HUD (see `product/uploads/tech-design.md`) |
| `marketing/` | Marketing site — landing page + blog | Static site / your web framework |

Each folder has its own `README.md` that is self-sufficient. The two share a visual language (palette, typography, the candy-UI button/chip style) — see the Design Tokens section in `product/README.md`; the marketing README repeats the subset it needs.

The `.dc.html` files are **design references** (interactive HTML prototypes), not production code. Serve a folder statically and open them in a browser to see intended look + behavior. Recreate them in the target codebase's environment using its established patterns.
