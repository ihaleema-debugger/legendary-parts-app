FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# Output stage — copy build to shared volume
FROM alpine:3.19
COPY --from=build /app/dist /app/dist
CMD ["cp", "-r", "/app/dist/.", "/usr/share/nginx/html/"]
