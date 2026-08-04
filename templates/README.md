# App store templates

Install definitions for running TikTok Favorites Archive on self-hosted app platforms. Each folder targets one platform. None of these are published to an official store yet; they work today via each platform's manual install path.

The app always needs its Cobalt companion. The CasaOS and Umbrel files bundle both containers in one compose file. On Unraid they are two separate templates and Cobalt goes in first.

## unraid/

Two Community Applications XML templates: `tiktok-favorites-archiver.xml` (the app) and `cobalt.xml` (the companion, with the same relaxed rate limits the project's docker-compose ships).

To use them today:

1. In the Unraid web UI, open the **Docker** tab and scroll to **Template Repositories** at the bottom.
2. Paste `https://github.com/JackB296/tiktok-favorites-archiver` into the box and press **Save**.
3. Click **Add Container**, open the **Template** dropdown, and pick `cobalt` under User templates. Set `API_URL` to `http://YOUR-SERVER-IP:9000/` and apply.
4. Add a second container from the `tiktok-favorites-archiver` template. Set `COBALT_API_URL` to the same address, review the paths, and apply.
5. Open the WebUI and upload your TikTok data export on the Sync tab.

The archiver template ships `ALLOWED_HOSTS=*` so the WebUI works immediately. Replace `*` with your server's IP or hostname when you get a chance; the allowlist doubles as the app's DNS-rebinding guard, and the app has no login.

Later, listing in Community Applications means asking for the repository to be indexed: post in the Community Applications thread on the Unraid forums with a link to this repo, per the CA moderation guidelines.

## casaos/

One `docker-compose.yml` with both services and `x-casaos` metadata.

To use it today:

1. In CasaOS, click the **+** button next to the app list and choose **Install a customized app**.
2. Click the **Import** icon in the top right of the dialog, paste the full contents of `casaos/docker-compose.yml`, and confirm.
3. Install, then upload your TikTok data export on the Sync tab. Media lands in `/DATA/Media/TikTokFavorites` on the host.

Later, store listing works by pull request: the BigBearCasaOS community store takes PRs at `bigbeartechworld/big-bear-casaos`, and the official store takes PRs at `IceWhaleTech/CasaOS-AppStore`.

## umbrel/

An Umbrel app directory (`umbrel-app.yml` plus `docker-compose.yml`), ready but not yet submitted to any store, so it does not show up in an Umbrel app store today. `ALLOWED_HOSTS` is `*` here on purpose: Umbrel fronts every app with its own authenticating proxy, so the proxy is the access control layer and the app cannot predict which hostname it will be reached by.

To use it before any store listing exists, it has to live in a community app store: fork `getumbrel/umbrel-community-app-store`, copy `umbrel/tiktok-favorites-archiver/` into it, rename the folder and the manifest `id` to carry your store's prefix (community stores require `store-id-app-name`), and add the store's GitHub URL in the umbrelOS App Store settings.

Later, official listing is a pull request to `getumbrel/umbrel-apps`; that submission requires the image pinned to a version tag plus sha256 digest instead of `:latest`.
