FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install --yes --no-install-recommends fluxbox novnc websockify x11vnc xvfb \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 6080

HEALTHCHECK --interval=5s --timeout=3s --retries=12 CMD test -S /tmp/.X11-unix/X99

CMD ["sh", "-ec", "Xvfb :99 -screen 0 1440x960x24 -ac -listen tcp & while [ ! -S /tmp/.X11-unix/X99 ]; do sleep 0.2; done; fluxbox -display :99 & x11vnc -display :99 -forever -shared -nopw -rfbport 5900 & exec websockify --web=/usr/share/novnc 6080 localhost:5900"]
