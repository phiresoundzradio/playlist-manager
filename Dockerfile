FROM node:20-alpine

WORKDIR /app

# Install dependencies first (layer-cached)
COPY package.json ./
RUN npm install --omit=dev

# Copy app files
COPY server.js ./
COPY PlaylistManager.html ./

# Data volume for library index and synced playlists
VOLUME ["/data"]

EXPOSE 3000

CMD ["node", "server.js"]
