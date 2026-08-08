FROM node:25-alpine@sha256:bdf2cca6fe3dabd014ea60163eca3f0f7015fbd5c7ee1b0e9ccb4ced6eb02ef4 AS build

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@11.7.0 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN pnpm build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10

RUN rm -f /etc/nginx/conf.d/default.conf \
    && chown -R nginx:nginx /etc/nginx/conf.d /var/cache/nginx /var/run
COPY --chown=nginx:nginx nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

USER nginx

EXPOSE 8080
