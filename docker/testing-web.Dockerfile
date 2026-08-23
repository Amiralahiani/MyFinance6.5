FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_TESTING_API_URL=http://localhost:8001
ARG VITE_CHAT_WEB_URL=http://localhost:3000
ARG VITE_PLAYWRIGHT_VIEWER_URL=http://localhost:6080/vnc.html?autoconnect=true&resize=scale
ENV VITE_TESTING_API_URL=${VITE_TESTING_API_URL} \
    VITE_CHAT_WEB_URL=${VITE_CHAT_WEB_URL} \
    VITE_PLAYWRIGHT_VIEWER_URL=${VITE_PLAYWRIGHT_VIEWER_URL}

COPY autotest/web/package.json autotest/web/package-lock.json ./
RUN npm ci
COPY autotest/web/ ./
RUN npm run build

FROM nginx:1.27-alpine

COPY docker/nginx-spa.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
