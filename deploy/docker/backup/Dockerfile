FROM alpine:3.19

RUN apk add --no-cache postgresql-client bash tar dcron

COPY backup.sh /backup.sh
RUN chmod +x /backup.sh

# Setup cron job (runs daily at 2 AM)
RUN echo "0 2 * * * bash /backup.sh >> /var/log/backup.log 2>&1" > /etc/crontabs/root

CMD ["crond", "-f", "-d", "8"]
