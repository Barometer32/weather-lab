# Satellite products

The satellite dropdown opens with **Visible (red)**, COD's GOES-East ABI Band
02 for Central Minnesota (`S_Minnesota`). True color, Day Cloud Phase and NT
Microphysics follow in that order. A fresh load overrides browser-restored
selections; users can then switch among all four bands.

Visible (red) is grayscale daylight imagery. The red label refers to the
spectral band. Source JPEG bytes remain unchanged on the native 1600 × 900
grid, aligned with the existing county and state overlays. No reprojection or
recoloring is performed. NT Microphysics remains available after dark; the
default does not switch automatically at sunset.

The existing satellite scheduler collects all four products every five
minutes. Each has its own prepared manifest and latest 24 available images.
Newest frames publish first; partial source failures preserve valid saved
history. Missing images are replaced by the next older available image.

Opening the website primes all product manifests independently and warms only
the latest default visible image when Data Saver is off. The public API reads
prepared data and immutable saved image files. Selecting another band keeps
its existing source, timeline and image behavior.

`release-plots.sh` verifies the new dropdown default and a prepared 24-frame
visible loop before website cutover. After successful live verification it
extends the actual data bucket's lifecycle with a one-day rule limited to
`satellite/02/`. Existing retention rules are preserved, and the original
bucket metadata is saved with release diagnostics. Repeating the extension
does not add duplicate rules.
