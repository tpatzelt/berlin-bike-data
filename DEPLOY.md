# Deploying to the homelab

One container (`bikes`) runs the collector, the nightly rebuild at 03:30 Europe/Berlin
and a static file server on port 8080. It is published to
`ghcr.io/tpatzelt/berlin-bike-data` by `.github/workflows/ci.yml` on every push to
`master` (tests first), as `:latest` and `:sha-<short>`. `example.com` stands in for
the real domain below.

## 1. Stack

In the homelab repo:

```bash
mkdir -p compose/bikes
cp <this repo>/deploy/compose.yaml compose/bikes/compose.yaml
cp <this repo>/deploy/.bikes.env.example secrets/.bikes.env.example
cp secrets/.bikes.env.example secrets/.bikes.env        # fill in, see below
ln -s ../../secrets/.bikes.env compose/bikes/.env
```

In `secrets/.bikes.env` set `BIKES_USER_AGENT` to something that identifies you
(nextbike sees it), and fill `BIKES_OPERATOR_NAME`, `BIKES_OPERATOR_ADDRESS` and
`BIKES_OPERATOR_EMAIL`: a public site in Germany needs a real Impressum. Leave
`BIKES_DATA_DIR`/`BIKES_SITE_DIR` alone; compose overrides them.

Data lives in `/opt/dockerdata/bikes` (inside autorestic's backup). The container runs
as uid 10001, so the directory must be writable by it:

```bash
mkdir -p /opt/dockerdata/bikes && chown 10001:10001 /opt/dockerdata/bikes   # or chmod 2777 if not root
docker compose -f compose/bikes/compose.yaml up -d
docker logs -f bikes          # "serving /data/site on :8080", then collector lines
```

## 2. Caddy route

In `compose/caddy/Caddyfile`, inside the public `*.{$DOMAIN}` block, before the
catch-all `abort`:

```
	@bikes host bikes.{$DOMAIN}
	handle @bikes {
		reverse_proxy bikes:8080
	}
```

Then force-recreate Caddy (the Caddyfile is a single-file bind mount):

```bash
docker compose -f compose/caddy/compose.yaml up -d --force-recreate caddy
```

Add a blackbox probe for `http://bikes:8080/healthz` in
`compose/monitoring/prometheus/prometheus.yml` so the route shows up on the dashboard.

## 3. Cloudflare Tunnel

In `/opt/dockerdata/cloudflared/config.yml`, above the final `http_status:404` rule:

```yaml
  - hostname: bikes.example.com
    service: https://caddy:443
    originRequest:
      originServerName: bikes.example.com
```

(match the style of the existing rules), then:

```bash
cloudflared tunnel route dns homelab bikes.example.com
docker compose -f compose/cloudflared/compose.yaml restart cloudflared
```

## 4. Check

```bash
docker inspect --format '{{.State.Health.Status}}' bikes         # healthy
curl -sI https://bikes.example.com/ | head -1                     # 200
ls /opt/dockerdata/bikes/parquet/nextbike_bn/station_status/      # date=YYYY-MM-DD dirs
```

Until 14 full days are collected, every chart says "not enough data yet". That is
expected.

## 5. Before posting to Reddit

Collect for **at least 14 full days; 28 are recommended**, so every weekday appears
four times and one rainy week does not dominate. Then read the numbers off the live
article, fill the placeholders in `docs/REDDIT_POST.md`, and check the Impressum page
shows real details.

## Updating and rolling back

A push to `master` publishes a new `:latest`. Pull it on the host:

```bash
docker compose -f compose/bikes/compose.yaml pull && docker compose -f compose/bikes/compose.yaml up -d
```

To roll back, pin `image: ghcr.io/tpatzelt/berlin-bike-data:sha-<short>` in the
compose file. The collector resumes without duplicates or gaps after a restart, and
any downtime is recorded as a gap row.
