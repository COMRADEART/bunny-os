# Bunny OS visual identity

Bunny OS uses an original rounded-arc motif: intersecting paths suggest work moving between local spaces without borrowing another operating system's marks. The app icon uses an abstract long-ear silhouette inside a rounded evergreen tile. It is intentionally not a copy of GNOME, KDE, Windows, macOS, Ubuntu, ChromeOS, Kali, Parrot, or COSMIC branding.

The repository includes scalable light (3840×2160) and dark ultrawide (5120×2160) SVG wallpapers, and `bunny-nocturne.svg` (3840×2160), the desktop default. SVG supplies arbitrary standard, HiDPI, and ultrawide output without raster interpolation. Lock-screen clock placement must be visually tested; sensitive notification content is suppressed independently of artwork.

`bunny-nocturne.svg` is composed around the interface rather than decorated and then covered: the ridge line sits at 62% height so it passes behind the character and not through its head, the brightest part of the sky is upper-right away from the greeting, and the lower third is darkened further than a landscape would be because the dock and the card columns sit on it. A contrast scrim drawn by the shell sits over whatever wallpaper the user chooses, so panel text keeps 4.5:1 over a white photograph as well. If the file cannot be loaded, the dconf gradient default (`#141033` to `#080B12`, vertical) shows instead and the desktop is still composed.

The central character is a vector figure drawn from a data definition, not a bundled model: `lib/character/definition.js` holds every colour and proportion, so a replacement character is a different object of that shape. The 3D GLB in `assets/companion/characters/default-bunny-3d` is used by the companion *window*, which is a GTK client with its own GL context; a Wayland surface cannot be reparented into the compositor's scene graph, so the desktop figure is drawn in-process instead.

Original Bunny Shell, Settings, Workspaces, Approval, and symbolic status icons live under `shell/icons/hicolor`. Adwaita is the documented fallback for system functions. Icons are SVG, work against dark/light backgrounds, and status never depends on shape or color alone.

Asset provenance and CC BY 4.0 terms are in `shell/assets/LICENSE.md`. No third-party font, raster artwork, or trademark asset is bundled. Image-generated artwork is not required.
