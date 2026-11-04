# Weather Lab on iPhone and the web

Run `update-weather-iphone-web-app.sh weather-lab-261028-205713-506d` in
authenticated Google Cloud Shell, with `WEATHER_SOURCE_COMMIT` pinned to the
reviewed source. The update builds and replaces only the public website image.
The collector, schedules, runtime settings and prepared weather remain in place.

On iPhone, open https://weather-lab.cloud.run in Safari. Choose Share, Add to
Home Screen, enable Open as Web App if shown, then tap Add. Launch Weather Lab
from its new Home Screen icon. It opens in a standalone window without Safari's
address bar. Installation still requires this user action; the website cannot
install itself silently. If an older Home Screen shortcut has the wrong icon or
launch mode, remove that shortcut and add the updated site again.

The laptop website remains available at the same address. Both experiences use
the existing five tabs, lowest base reflectivity, two-hour radar loop, four-frame
METAR viewer and 90% readiness hold. Phone full-screen buttons remain hidden and
the compact phone controls are retained. The same safe-area-aware body and
viewport height logic handle Safari's toolbars, the installed app, rotation and
returning from the background. The normal laptop layout is unchanged.

The manifest uses a stable app ID and root scope, standalone display, and an
unlocked orientation. Opaque PNG app icons derive from the existing green/white
favicon, including a maskable icon with inset artwork. Apple status-bar mode is
default rather than translucent, avoiding deliberate content under the status bar.

There is no new service worker or offline weather cache. Existing bounded saved
snapshots still work as before; current weather needs internet and the Cloud Run
backend. Returning to the app refits the layout, while the existing visibility
handlers refresh the selected weather product. No location permission or tracking
is introduced. iPhone Home Screen apps may keep separate storage from Safari,
so a preferred map view may need to be saved once inside the installed app.

Validation includes manifest/static HTTP responses and MIME types, PNG dimensions,
standalone/Safari viewport state transitions, reopen/foreground behavior,
rotation, zoom protection, and the original radar and METAR rendering checks.
Physical iPhone safe-area behavior needs a final check after installation.
