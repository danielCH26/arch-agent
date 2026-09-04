FROM node:21-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .

# VITE_API_BASE_URL vacio = relative URLs = nginx proxea /api al backend.
# Para dev local, pasar VITE_API_BASE_URL=http://localhost:8000 al build.
ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

FROM nginx:alpine

# Custom nginx config: proxy /api al servicio "backend" del compose.
# Reemplaza el default.conf de nginx:alpine.
COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
