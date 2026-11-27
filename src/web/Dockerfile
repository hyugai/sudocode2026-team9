FROM node:24-bookworm-slim AS build

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

COPY package.json package-lock.json ./
RUN npm ci
COPY . .

# Public URLs and rewrites are baked into the production build.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG API_BACKEND_URL=http://backend:10000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    API_BACKEND_URL=$API_BACKEND_URL
RUN npm run build

FROM node:24-bookworm-slim AS runtime
WORKDIR /app
ARG API_BACKEND_URL=http://backend:10000
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    API_BACKEND_URL=$API_BACKEND_URL

COPY --from=build --chown=node:node /app ./
USER node
EXPOSE 3000
CMD ["node", "node_modules/next/dist/bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
