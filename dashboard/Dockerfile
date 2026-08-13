# MemOS dashboard — static build served by nginx, proxying /api to backend
#
# Build: docker build -f dashboard/Dockerfile -t memos-dashboard .
# Run:   docker run --rm -p 5173:80 -e MEMOS_API_TARGET=http://backend:8000 memos-dashboard

FROM node:20-alpine AS build

WORKDIR /srv/memos

COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci

COPY dashboard/ .
RUN npm run build

FROM nginx:alpine

COPY dashboard/nginx.conf /etc/nginx/conf.d/default.conf.template
COPY dashboard/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY --from=build /srv/memos/dist /usr/share/nginx/html

EXPOSE 80

ENTRYPOINT ["/docker-entrypoint.sh"]
