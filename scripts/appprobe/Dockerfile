FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11-utils xdotool xclip xterm openbox procps ca-certificates \
      tmux kitty neovim vim emacs-nox \
      alacritty konsole gnome-terminal dbus-x11 \
      libreoffice-writer thunderbird \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /work
