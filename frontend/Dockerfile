# Local development image only.
#
# It runs the Vite dev server so Docker Compose gets hot module replacement at
# http://localhost:5173. Production builds are handled natively by Vercel
# (see vercel.json); there is deliberately no production stage here.
FROM node:22-alpine

WORKDIR /app

# Dependency layer: cached until the lockfile changes.
COPY package.json package-lock.json ./
RUN npm ci

# Application source (node_modules and env files are excluded by
# .dockerignore, so they can never leak into the image).
COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
