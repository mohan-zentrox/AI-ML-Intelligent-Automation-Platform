# Project Synapse - frontend container image (multi-stage build)

FROM node:20-slim AS build
WORKDIR /app

# Vite inlines `import.meta.env.VITE_*` into the bundle at BUILD time, so the
# API base URL has to be supplied here as a build argument - setting it as a
# runtime environment variable on the nginx stage would have no effect at all
# (the strings are already baked into the JS by then). Override per
# environment with:
#     docker build --build-arg VITE_API_BASE_URL=https://api.example.com/api/v1 .
# or via the `build.args` block in docker-compose.yml.
ARG VITE_API_BASE_URL=http://localhost:8000/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Copy the lockfile too and prefer `npm ci` so image builds are reproducible
# and match what CI tested, instead of silently floating to newer minors.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
# SPA routing: react-router uses history mode, so any unknown path must fall
# back to index.html rather than 404 from nginx.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
