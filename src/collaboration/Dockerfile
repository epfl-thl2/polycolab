FROM node:26.5.0-bookworm-slim
RUN npm install --global pnpm@12.1.0
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml .npmrc ./
COPY src/collaboration/package.json src/collaboration/package.json
COPY src/web/package.json src/web/package.json
RUN pnpm install --frozen-lockfile --filter @polycolab/collaboration --prod
COPY src/collaboration/src src/collaboration/src
USER node
ENV COLLABORATION_HOST=0.0.0.0
CMD ["node", "--experimental-strip-types", "src/collaboration/src/server.ts"]
