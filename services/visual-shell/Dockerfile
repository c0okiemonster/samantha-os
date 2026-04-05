FROM node:22-slim

WORKDIR /app

COPY package.json .
RUN npm install

COPY . .

EXPOSE 3333

CMD ["npx", "http-server", ".", "-p", "3333", "-c-1", "--cors"]
