#!/usr/bin/env bash
# Put the dashboard page on Vercel, with its requests forwarded to your server.
#
# Vercel serves only the page, which holds no data. Everything the page loads goes
# through Vercel to the server's public https address (STUDY_API_URL in .env), and
# the server answers only after you sign in with its DASHBOARD_PASSWORD.
#
# Run it from Git Bash, signed in to the Vercel CLI:   bash scripts/deploy-frontend.sh
set -euo pipefail
cd "$(dirname "$0")/.."

setting() { grep -m1 "^$1=" .env 2>/dev/null | cut -d= -f2- | tr -d '\r' || true; }
api="${STUDY_API_URL:-$(setting STUDY_API_URL)}"
api="${api%/}"
project="${VERCEL_PROJECT:-$(setting VERCEL_PROJECT)}"
case "$api" in
  https://*) ;;
  *) echo "Set STUDY_API_URL=https://... in .env first." >&2; exit 1 ;;
esac

# Every path the server answers on; a test checks none is missing. The page itself
# is the only thing Vercel keeps, at / and, as on the server, at /dashboard.
paths="api|chat|courses|assessments|course-resources|resources|changes|jobs|practice|login|logout|health|docs|openapi.json"
site=.vercel-site
mkdir -p "$site"
cp backend/app/web/dashboard.html "$site/index.html"
cat > "$site/vercel.json" <<EOF
{
  "\$schema": "https://openapi.vercel.sh/vercel.json",
  "rewrites": [
    { "source": "/($paths)(.*)", "destination": "$api/\$1\$2" },
    { "source": "/dashboard", "destination": "/" }
  ],
  "headers": [
    {
      "source": "/($paths)(.*)",
      "headers": [{ "key": "x-vercel-enable-rewrite-caching", "value": "0" }]
    }
  ]
}
EOF

if [ ! -d "$site/.vercel" ]; then
  vercel link --yes --project "${project:-study-agent}" --cwd "$site"
  # Linking inside this repo connects it to GitHub, and then every push would
  # replace the site with the repo itself, which has no page at its root.
  vercel git disconnect --yes --cwd "$site" || true
fi
# The CLI now and then returns without deploying. Try twice, and say so plainly if the
# old page is still the one being served.
for attempt in 1 2; do
  if out=$(vercel deploy --prod --yes --cwd "$site" 2>&1) && grep -q '"readyState": "READY"' <<< "$out"; then
    grep -E '"url"|"readyState"' <<< "$out"
    exit 0
  fi
  echo "Vercel deploy attempt $attempt did not finish:" >&2
  tail -n 6 <<< "$out" >&2
done
exit 1
