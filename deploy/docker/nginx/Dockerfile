FROM nginx:1.27-alpine

# Remove default config
RUN rm /etc/nginx/nginx.conf
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom configs
COPY nginx.conf /etc/nginx/
COPY conf.d/ /etc/nginx/conf.d/
