FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
# gnome-terminal is a thin client for gnome-terminal-server, which REFUSES to
# start under a non-UTF-8 locale — "Non UTF-8 locale (ANSI_X3.4-1968) is not
# supported!" — and a container defaults to exactly that. The terminal then
# never opens, which reads as "GNOME Terminal does not work here". It does.
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11-utils xdotool xclip xterm openbox procps ca-certificates \
      tmux kitty neovim vim emacs-nox \
      alacritty konsole gnome-terminal dbus-x11 \
      libreoffice-writer thunderbird \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
